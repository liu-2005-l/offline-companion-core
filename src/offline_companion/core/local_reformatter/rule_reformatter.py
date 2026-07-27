"""rule_reformatter：规则版 PersonaReformatter（B4）。"""

from __future__ import annotations

import re

import yaml

from offline_companion.core.emotion_analyzer.context import EmotionContext
from offline_companion.shared.errors import ReformatError
from offline_companion.shared.runtime_paths import configs_dir, dev_repo_root
from offline_companion.shared.types import Persona

LOCAL_FALLBACK_PREFIX = "我现在用自己的方式回答你："

_POLISH_RULES: dict[str, dict] | None = None


def _load_polish_rules() -> dict[str, dict]:
    """摘要：加载情绪润色规则。"""
    global _POLISH_RULES
    if _POLISH_RULES is not None:
        return _POLISH_RULES

    candidates = [
        configs_dir() / "polish_rules.yaml",
        configs_dir() / "emotion_mappings.yaml",
        dev_repo_root() / "configs" / "polish_rules.yaml",
        dev_repo_root() / "configs" / "emotion_mappings.yaml",
    ]
    raw: dict | None = None
    for candidate in candidates:
        if not candidate.is_file():
            continue
        loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        raw = loaded if isinstance(loaded, dict) else {}
        break

    if raw is None:
        _POLISH_RULES = {}
        return _POLISH_RULES

    rules = raw.get("polish_rules", {})
    _POLISH_RULES = {key: value for key, value in rules.items() if isinstance(value, dict)}
    return _POLISH_RULES


def _apply_emotion_polish(text: str, emotion_context: EmotionContext | None) -> str:
    """摘要：根据情绪上下文对文本做润色。"""
    if emotion_context is None or emotion_context.emotion == "neutral":
        return text

    rules = _load_polish_rules()
    entry = rules.get(emotion_context.emotion)
    if not entry:
        return text

    result = text
    max_exclamation = int(entry.get("max_exclamation", 1))
    exclamation_count = result.count("！") + result.count("!")
    if exclamation_count > max_exclamation:
        kept = 0
        chars = list(result)
        for index, char in enumerate(chars):
            if char not in ("！", "!"):
                continue
            if kept >= max_exclamation:
                chars[index] = "。"
            else:
                kept += 1
        result = "".join(chars)

    suffix = str(entry.get("append_suffix") or "").strip()
    if suffix and emotion_context.valence < 0.5 and not result.rstrip().endswith(suffix):
        result = result.rstrip() + "\n\n" + suffix
    return result


def _reformat_config(persona: Persona) -> dict:
    raw = persona.raw.get("reformat")
    return raw if isinstance(raw, dict) else {}


def _tone_keywords(persona: Persona) -> list[str]:
    raw = persona.raw.get("tone_keywords")
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw if str(item).strip()]
    return ["呀", "呢"]


def latin_letter_ratio(text: str) -> float:
    """摘要：估算拉丁字母占比。"""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for char in letters if ord(char) < 128)
    return latin / len(letters)


def should_reformat(text: str, persona: Persona) -> bool:
    """摘要：判断是否需要对云端原文做规则润色。"""
    body = text.strip()
    if not body:
        return True
    config = _reformat_config(persona)
    min_chars = int(config.get("min_chars", 8))
    max_latin_ratio = float(config.get("max_latin_ratio", 0.35))
    if len(body) < min_chars:
        return True
    return latin_letter_ratio(body) > max_latin_ratio


def reformat_cloud_reply(
    text: str,
    persona: Persona,
    emotion_context: EmotionContext | None = None,
) -> str:
    """摘要：将云端返回文本压回人格风格。"""
    body = text.strip()
    if not body:
        raise ReformatError("云端返回为空")

    config = _reformat_config(persona)
    min_chars = int(config.get("min_chars", 8))
    tones = _tone_keywords(persona)
    result = _apply_emotion_polish(body, emotion_context)

    if latin_letter_ratio(result) > float(config.get("max_latin_ratio", 0.35)):
        result = f"我整理成中文跟你说：{result}"

    if len(result) < min_chars:
        tail = tones[0] if tones else "呀"
        result = f"{result}，{tail}，要是还想聊我可以陪你多说几句。"

    if tones and not re.search(r"[呀呢吧啦哈哦]$", result.rstrip("。！？?!")):
        if result[-1] in "。！？?!":
            result = result[:-1] + "，" + tones[0] + "。"
        else:
            result = result + "，" + tones[0] + "。"

    if not result.strip():
        raise ReformatError("润色结果为空")
    return result.strip()


def reformat_local_reply(
    text: str,
    emotion_context: EmotionContext | None = None,
) -> str:
    """摘要：对本地模型输出执行 B4 情绪润色。"""
    body = text.strip()
    if not body:
        raise ReformatError("本地回复为空")
    result = _apply_emotion_polish(body, emotion_context)
    if not result.strip():
        raise ReformatError("本地润色结果为空")
    return result.strip()
