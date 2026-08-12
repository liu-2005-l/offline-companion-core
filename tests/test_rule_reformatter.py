"""B4 规则润色测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from offline_companion.core.emotion_analyzer.context import EmotionContext
from offline_companion.core.local_reformatter import rule_reformatter
from offline_companion.core.local_reformatter.rule_reformatter import (
    reformat_cloud_reply,
    reformat_local_reply,
    should_reformat,
)
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.shared.errors import ReformatError
from offline_companion.shared.types import CapabilityProfile


def _persona():
    return load_persona_file(Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml")


def test_should_reformat_short_and_english() -> None:
    persona = _persona()
    assert should_reformat("OK.", persona)
    assert should_reformat("This is a long English only reply for testing.", persona)


def test_reformat_adds_chinese_frame_for_english() -> None:
    persona = _persona()
    output = reformat_cloud_reply("This is a cold English cloud reply.", persona)
    assert "整理成中文" in output
    assert "English" in output


def test_reformat_preserves_facts() -> None:
    persona = _persona()
    output = reformat_cloud_reply("记得喝水，每天 8 杯水。", persona)
    assert "8" in output
    assert "水" in output


def test_reformat_empty_raises() -> None:
    persona = _persona()
    with pytest.raises(ReformatError):
        reformat_cloud_reply("   ", persona)


def test_emotion_polish_none_context() -> None:
    persona = _persona()
    output = reformat_cloud_reply("今天天气不错。", persona, emotion_context=None)
    assert "今天天气不错" in output


def test_emotion_polish_neutral_no_change() -> None:
    persona = _persona()
    output = reformat_cloud_reply("今天天气不错。", persona, emotion_context=EmotionContext(emotion="neutral"))
    assert "今天天气不错" in output


def test_emotion_polish_anger_limits_exclamation() -> None:
    persona = _persona()
    output = reformat_cloud_reply(
        "你这样做真的太气人了！！！！！",
        persona,
        emotion_context=EmotionContext(emotion="anger", valence=-0.8, arousal=0.9),
    )
    assert "！" not in output
    assert "我会一直在这里陪你" in output


def test_emotion_polish_anxiety_appends_suffix() -> None:
    persona = _persona()
    output = reformat_cloud_reply(
        "我现在真的好害怕。",
        persona,
        emotion_context=EmotionContext(emotion="anxiety", valence=-0.6, arousal=0.8),
    )
    assert "别担心，我一直都在" in output


def test_emotion_polish_joy_keeps_three_exclamations() -> None:
    persona = _persona()
    output = reformat_cloud_reply(
        "今天真的太棒了！！！！！！",
        persona,
        emotion_context=EmotionContext(emotion="joy", valence=0.8, arousal=0.7),
    )
    assert output.count("！") == 3


def test_polish_rules_prefers_dedicated_config() -> None:
    rule_reformatter._POLISH_RULES = None
    rules = rule_reformatter._load_polish_rules()
    assert "anger" in rules
    assert rules["sadness"]["append_suffix"] == "我会陪着你。"


def test_reformat_local_reply_uses_emotion_polish() -> None:
    output = reformat_local_reply(
        "我现在很难过！！",
        emotion_context=EmotionContext(emotion="sadness", valence=-0.7, arousal=0.3),
    )
    assert "我会陪着你" in output


def test_reformat_local_reply_empty_raises() -> None:
    with pytest.raises(ReformatError):
        reformat_local_reply("   ")


def test_reformat_local_reply_trusts_high_roleplay_model() -> None:
    emotion = EmotionContext(emotion="sadness", valence=0.2)
    output = reformat_local_reply(
        "  保留原始回答！  ",
        emotion_context=emotion,
        capability_profile=CapabilityProfile(roleplay_quality=0.8),
    )
    assert output == "保留原始回答！"


def test_reformat_cloud_reply_trusts_high_roleplay_model() -> None:
    persona = _persona()
    output = reformat_cloud_reply(
        "  保留云端模型原文。  ",
        persona,
        emotion_context=EmotionContext(emotion="sadness", valence=0.2),
        capability_profile=CapabilityProfile(roleplay_quality=0.8),
    )
    assert output == "保留云端模型原文。"
