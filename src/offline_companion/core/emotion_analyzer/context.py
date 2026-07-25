"""context：B0 情绪上下文数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EmotionContext:
    """摘要：情绪预分析输出。

    参数：
        emotion: 7 类情绪标签。
        confidence: 置信度，范围 0~1。
        valence: 效价值，范围 -1~1。
        arousal: 唤醒度，范围 0~1。
        dominance: 支配感，范围 -1~1。
        suggested_strategy: 建议共情策略。
        raw: 调试与回退用原始附加信息。
    """

    emotion: str = "neutral"
    confidence: float = 0.0
    valence: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0
    suggested_strategy: str = "neutral_follow"
    raw: dict[str, Any] = field(default_factory=dict)
