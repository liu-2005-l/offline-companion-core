"""摘要：P3-A2 T24 确定性人格文案资产、审计与调用边界测试。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.run_persona_constraint_p2_form_preexperiment2 import (
    detect_copy,
    scan_forbidden,
    scan_l4,
)

from offline_companion.core.persona_constraint import (
    REPLY_COPY_CONSTRAINT_CONFIG_FALLBACK,
    REPLY_COPY_MEMORY_SAVED_CONFIRMATION,
    REPLY_COPY_SWITCH_CONFIRMATION,
    PersonaConstraintConfigError,
    load_persona_constraint_assets,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPLY_COPY_KINDS = (
    REPLY_COPY_SWITCH_CONFIRMATION,
    REPLY_COPY_MEMORY_SAVED_CONFIRMATION,
    REPLY_COPY_CONSTRAINT_CONFIG_FALLBACK,
)
ABSOLUTE_PROMISE_PATTERN = re.compile(r"(?:保证|肯定|绝对|百分之百|永远|一定会|不会再|随时都)")
MECHANISM_LEAK_PATTERN = re.compile(
    r"(?:OCEAN|L[1-4]|manifest|sha-?256|schema|DTO|backend|system\s*prompt|"
    r"系统提示词|模型参数|采样参数|内部机制|哈希|快照|档位映射)",
    flags=re.IGNORECASE,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _assistant_examples(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        assistant = value.get("assistant")
        if isinstance(assistant, str):
            result.append(assistant)
        for nested in value.values():
            result.extend(_assistant_examples(nested))
    elif isinstance(value, list):
        for nested in value:
            result.extend(_assistant_examples(nested))
    return result


def test_t24_reply_copy_is_complete_and_byte_deterministic_for_five_presets() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    preset_ids = {preset.persona_id for preset in assets.builtin_presets}

    assert set(assets.reply_copy) == preset_ids
    assert len(assets.reply_copy) * len(REPLY_COPY_KINDS) == 15
    for persona_id in sorted(preset_ids):
        for kind in REPLY_COPY_KINDS:
            first = assets.deterministic_reply(persona_id, kind)
            second = assets.deterministic_reply(persona_id, kind)
            assert first is not None
            assert first.encode("utf-8") == second.encode("utf-8")
    assert assets.deterministic_reply("user_created", REPLY_COPY_SWITCH_CONFIRMATION) is None


def test_t24_reply_copy_passes_all_five_one_time_audits() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    lexicon = _load_yaml(REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml")
    patterns = _load_yaml(REPO_ROOT / "configs" / "persona_constraint_l4_patterns.yaml")
    examples = _assistant_examples(assets.source_payloads["dimension_corpus"])
    examples.extend(_assistant_examples(assets.source_payloads["structural_corpus"]))
    texts = [
        assets.deterministic_reply(persona_id, kind)
        for persona_id in sorted(assets.reply_copy)
        for kind in REPLY_COPY_KINDS
    ]

    assert len(examples) == 78
    assert all(text is not None for text in texts)
    for text in texts:
        assert text is not None
        assert scan_forbidden(text, lexicon) == []
        assert scan_l4(text, patterns, display_name_present=False)["hit"] is False
        assert detect_copy(text, examples, output_tokens=len(text))["hit"] is False
        assert ABSOLUTE_PROMISE_PATTERN.search(text) is None
        assert MECHANISM_LEAK_PATTERN.search(text) is None


def test_t24_one_time_audits_have_independent_positive_controls() -> None:
    lexicon = _load_yaml(REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml")
    patterns = _load_yaml(REPO_ROOT / "configs" / "persona_constraint_l4_patterns.yaml")
    examples = ["先选你已经接触过的一项，做完一个小练习。"]

    assert scan_forbidden("作为一个AI助手，我不能陪伴你。", lexicon)
    assert scan_l4("我无法保持人格。", patterns, display_name_present=False)["hit"] is True
    assert detect_copy("先选你已经接触", examples, output_tokens=8)["hit"] is True
    assert ABSOLUTE_PROMISE_PATTERN.search("我保证一定会完成。") is not None
    assert MECHANISM_LEAK_PATTERN.search("L1 system prompt 的 SHA-256 已更新。") is not None


def test_t24_reply_copy_call_sites_are_limited_to_three_non_protected_paths() -> None:
    http_source = (
        REPO_ROOT
        / "src"
        / "offline_companion"
        / "shell"
        / "ui_host"
        / "desktop"
        / "http_host.py"
    ).read_text(encoding="utf-8")
    turn_source = (
        REPO_ROOT / "src" / "offline_companion" / "shell" / "ui_host" / "turn_payload.py"
    ).read_text(encoding="utf-8")
    shell_api_source = (
        REPO_ROOT
        / "src"
        / "offline_companion"
        / "shell"
        / "ui_host"
        / "desktop"
        / "static"
        / "shell_api.js"
    ).read_text(encoding="utf-8")

    assert http_source.count(".deterministic_reply(") == 2
    assert "exc.code == \"switch_failed\"" in http_source
    assert http_source.count("REPLY_COPY_SWITCH_CONFIRMATION") == 2
    assert http_source.count("REPLY_COPY_CONSTRAINT_CONFIG_FALLBACK") == 2
    assert turn_source.count(".deterministic_reply(") == 1
    assert "if not result.memory_only or not result.memory_saved:" in turn_source
    assert turn_source.count("REPLY_COPY_MEMORY_SAVED_CONFIRMATION") == 2
    assert "showToast(data.confirmation || ('已切换到人格 · ' + name));" in shell_api_source
    assert "error.data && error.data.user_message" in shell_api_source


def test_t24_reply_copy_is_registered_in_the_published_hash_chain(tmp_path: Path) -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)

    assert assets.source_paths["reply_copy"] == REPO_ROOT / "configs" / "persona_constraint_reply_copy.yaml"
    assert assets.source_payloads["reply_copy"]["version"] == "p3-a2-reply-copy-v1"

    shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
    target = tmp_path / "configs" / "persona_constraint_reply_copy.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    with pytest.raises(PersonaConstraintConfigError, match="source_hash_mismatch:reply_copy"):
        load_persona_constraint_assets(root_override=tmp_path)
