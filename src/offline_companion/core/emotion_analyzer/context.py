"""context：B0 情绪上下文数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VADVector:
    """摘要：Valence/Arousal/Dominance 三维向量，范围统一为 0.0-1.0。"""

    valence: float
    arousal: float
    dominance: float

    def __post_init__(self) -> None:
        for field_name in ("valence", "arousal", "dominance"):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")


@dataclass(frozen=True)
class EmotionContext:
    """摘要：情绪预分析输出。

    参数：
        emotion: 情绪标签。
        confidence: 置信度，范围 0~1。
        vad: 三维 VAD 向量，范围 0~1。
        valence/arousal/dominance: 兼容旧调用方的标量别名；传入时会转换为 ``vad``。
        suggested_strategy: 建议共情策略。
        raw: 调试与回退用原始附加信息。
    """

    emotion: str = "neutral"
    confidence: float = 0.0
    vad: VADVector = field(default_factory=lambda: VADVector(0.5, 0.5, 0.5))
    suggested_strategy: str = "neutral_follow"
    raw: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        emotion: str = "neutral",
        confidence: float = 0.0,
        vad: VADVector | None = None,
        valence: float | None = None,
        arousal: float | None = None,
        dominance: float | None = None,
        suggested_strategy: str = "neutral_follow",
        raw: dict[str, Any] | None = None,
    ) -> None:
        if vad is None:
            if valence is None and arousal is None and dominance is None:
                vad = VADVector(0.5, 0.5, 0.5)
            else:
                vad = VADVector(
                    0.5 if valence is None else _normalize_vad_component(float(valence), allow_legacy_signed=True),
                    0.5 if arousal is None else _normalize_vad_component(float(arousal), allow_legacy_signed=False),
                    0.5 if dominance is None else _normalize_vad_component(float(dominance), allow_legacy_signed=True),
                )
        object.__setattr__(self, "emotion", emotion)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "vad", vad)
        object.__setattr__(self, "suggested_strategy", suggested_strategy)
        object.__setattr__(self, "raw", {} if raw is None else raw)

    @property
    def valence(self) -> float:
        """摘要：兼容旧调用方的 valence 只读访问。"""
        return self.vad.valence

    @property
    def arousal(self) -> float:
        """摘要：兼容旧调用方的 arousal 只读访问。"""
        return self.vad.arousal

    @property
    def dominance(self) -> float:
        """摘要：兼容旧调用方的 dominance 只读访问。"""
        return self.vad.dominance


def _normalize_vad_component(value: float, *, allow_legacy_signed: bool) -> float:
    """摘要：兼容旧的 [-1, 1] 写法，统一归一化到 [0, 1]。"""
    if allow_legacy_signed and -1.0 <= value <= 1.0 and value < 0.0:
        return (value + 1.0) / 2.0
    return value
