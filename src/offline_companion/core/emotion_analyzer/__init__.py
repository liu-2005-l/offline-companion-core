"""emotion_analyzer：B0 情绪预分析模块。"""

from __future__ import annotations

from offline_companion.core.emotion_analyzer.classifier import (
    EmotionClassifier,
    RuleEmotionClassifier,
)
from offline_companion.core.emotion_analyzer.context import EmotionContext

__all__ = [
    "EmotionClassifier",
    "EmotionContext",
    "RuleEmotionClassifier",
]
