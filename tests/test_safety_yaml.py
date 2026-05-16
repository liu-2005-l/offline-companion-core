from __future__ import annotations

from pathlib import Path

import yaml

from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.core.safety_boundary.fixed_replies import load_safety_replies


def test_safety_replies_load_default_path() -> None:
    bundle = load_safety_replies(reload=True)
    assert bundle.version >= 1
    assert bundle.self_markers
    assert bundle.self_reply.strip()
    assert bundle.other_reply.strip()


def test_classify_uses_yaml_reply(tmp_path: Path) -> None:
    custom = tmp_path / "custom_safety.yaml"
    custom.write_text(
        yaml.dump(
            {
                "version": 99,
                "locale": "zh-CN",
                "tiers": {
                    "crisis_self": {
                        "markers": ["测试自伤关键词"],
                        "reply": "自定义自伤话术",
                    },
                    "crisis_other": {
                        "markers": ["测试他伤关键词"],
                        "reply": "自定义他伤话术",
                    },
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    r = classify_user_text("这里有测试自伤关键词", replies_path=custom)
    assert r.tier is SafetyTier.CRISIS_SELF
    assert r.user_visible_reply == "自定义自伤话术"
    assert r.block_model is True


def test_classify_ok_from_yaml(tmp_path: Path) -> None:
    bundle = load_safety_replies(reload=True)
    r = classify_user_text("今天天气不错")
    assert r.tier is SafetyTier.OK
    assert r.block_model is False
    assert bundle.path.is_file()
