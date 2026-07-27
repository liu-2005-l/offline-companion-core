"""emotion_analyzer：B0 情绪预分析模块。"""

from __future__ import annotations

from offline_companion.core.emotion_analyzer.classifier import (
    EmotionClassifier,
    RuleEmotionClassifier,
    vad_for_emotion,
)
from offline_companion.core.emotion_analyzer.context import EmotionContext, VADVector

__all__ = [
    "EmotionClassifier",
    "EmotionContext",
    "RuleEmotionClassifier",
    "VADVector",
    "vad_for_emotion",
]
