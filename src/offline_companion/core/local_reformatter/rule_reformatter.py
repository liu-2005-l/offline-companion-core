"""rule_reformatter：规则版 PersonaReformatter（B4）。"""

from __future__ import annotations

import re

from offline_companion.shared.errors import ReformatError
from offline_companion.shared.types import Persona

# 硬降级时前缀（与 A2 编排约定一致）
LOCAL_FALLBACK_PREFIX = "我现在用自己的方式回答你："


def _reformat_config(persona: Persona) -> dict:
    raw = persona.raw.get("reformat")
    return raw if isinstance(raw, dict) else {}


def _tone_keywords(persona: Persona) -> list[str]:
    raw = persona.raw.get("tone_keywords")
    if isinstance(raw, list) and raw:
        return [str(x) for x in raw if str(x).strip()]
    return ["呢", "吧"]


def latin_letter_ratio(text: str) -> float:
    """摘要：估算拉丁字母占比（用于检测英文过重）。"""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for c in letters if ord(c) < 128)
    return latin / len(letters)


def should_reformat(text: str, persona: Persona) -> bool:
    """摘要：判断是否应对云端原文做规则润色。

    参数：
        text: 云端原始文本。
        persona: 当前人设（读取 ``reformat`` / ``tone_keywords`` 配置）。

    返回值：
        过短或英文占比过高时为 True。
    """
    body = text.strip()
    if not body:
        return True
    cfg = _reformat_config(persona)
    min_chars = int(cfg.get("min_chars", 8))
    max_latin = float(cfg.get("max_latin_ratio", 0.35))
    if len(body) < min_chars:
        return True
    return latin_letter_ratio(body) > max_latin


def reformat_cloud_reply(text: str, persona: Persona) -> str:
    """摘要：将云端返回文本用规则管线压回人设风格（不改事实、不删数字）。

    参数：
        text: 云端原始文本。
        persona: 当前人设。

    返回值：
        润色后文本。

    异常：
        ReformatError：输入为空或无法安全润色。
    """
    body = text.strip()
    if not body:
        raise ReformatError("云端返回为空")

    cfg = _reformat_config(persona)
    min_chars = int(cfg.get("min_chars", 8))
    tones = _tone_keywords(persona)
    out = body

    # 英文过重：加中文陪伴框架，保留原文信息
    if latin_letter_ratio(out) > float(cfg.get("max_latin_ratio", 0.35)):
        out = f"我整理成中文跟你说：{out}"

    # 过短：补足陪伴语气，不删除原句
    if len(out) < min_chars:
        tail = tones[0] if tones else "呢"
        out = f"{out}，{tail}要是还想聊我可以陪你多说几句。"

    # 句末语气词（仅当尚无常见语气收束）
    if tones and not re.search(r"[呢吧哦哈呐]$", out.rstrip("。！？.!?")):
        if out[-1] in "。！？.!?":
            out = out[:-1] + "，" + tones[0] + "。"
        else:
            out = out + "，" + tones[0] + "。"

    if not out.strip():
        raise ReformatError("润色结果为空")
    return out.strip()
