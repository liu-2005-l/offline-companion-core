"""B0 情绪分类测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from offline_companion.core.emotion_analyzer import EmotionClassifier, EmotionContext, RuleEmotionClassifier


def test_emotion_context_defaults() -> None:
    context = EmotionContext()
    assert context.emotion == "neutral"
    assert context.confidence == 0.0
    assert context.suggested_strategy == "neutral_follow"
    assert context.raw == {}


def test_emotion_context_is_frozen() -> None:
    context = EmotionContext(emotion="joy", confidence=0.9)
    with pytest.raises(AttributeError):
        context.emotion = "anger"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("我真的好生气，快气死了", "anger"),
        ("这两天特别焦虑，睡不着", "anxiety"),
        ("今天太开心啦哈哈", "joy"),
        ("我有点难过，想哭", "sadness"),
        ("不会吧，太震惊了", "surprise"),
        ("这也太恶心了，我很讨厌", "disgust"),
        ("今天天气不错，我去散步了", "neutral"),
    ],
)
def test_rule_classifier_predicts_expected_label(text: str, label: str) -> None:
    classifier = RuleEmotionClassifier()
    context = classifier.predict(text)
    assert context.emotion == label
    assert context.suggested_strategy


def test_rule_classifier_exposes_debug_hits() -> None:
    classifier = RuleEmotionClassifier()
    context = classifier.predict("我真的很生气，太生气了")
    assert context.raw["mode"] == "rule"
    assert context.raw["matched_hits"] >= 1


def test_emotion_classifier_falls_back_without_tokenizer(tmp_path: Path) -> None:
    model_path = Path(__file__).resolve().parents[1] / "fixtures" / "emotion_test_identity.onnx"
    classifier = EmotionClassifier(model_path=model_path, tokenizer_path=tmp_path / "missing.json")
    context = classifier.predict("我现在好难过")
    assert context.emotion == "sadness"
    assert context.raw["fallback"] is True
