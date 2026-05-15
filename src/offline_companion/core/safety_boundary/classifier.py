"""classifier：规则/词典安全分级器（B3）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import fixed_replies


class SafetyTier(str, Enum):
    """摘要：安全分级枚举。"""

    OK = "ok"
    CRISIS_SELF = "crisis_self"
    CRISIS_OTHER = "crisis_other"


@dataclass(frozen=True)
class SafetyResult:
    """摘要：单轮用户输入的安全判定结果。"""

    tier: SafetyTier
    user_visible_reply: str | None
    block_model: bool


_SELF_MARKERS = (
    "自杀",
    "自殺",
    "结束生命",
    "不想活了",
    "kill myself",
    "suicide",
    "end my life",
)
_OTHER_MARKERS = (
    "杀人",
    "报复社会",
    "炸弹怎么做",
    "how to make a bomb",
    "mass shooting",
)


def classify_user_text(text: str) -> SafetyResult:
    """摘要：对用户输入做关键词分级并返回固定话术（如命中）。"""
    t = text.lower()
    for m in _SELF_MARKERS:
        if m.lower() in t or m in text:
            return SafetyResult(
                tier=SafetyTier.CRISIS_SELF,
                user_visible_reply=fixed_replies.SELF_REPLY_ZH,
                block_model=True,
            )
    for m in _OTHER_MARKERS:
        if m.lower() in t or m in text:
            return SafetyResult(
                tier=SafetyTier.CRISIS_OTHER,
                user_visible_reply=fixed_replies.OTHER_REPLY_ZH,
                block_model=True,
            )
    return SafetyResult(tier=SafetyTier.OK, user_visible_reply=None, block_model=False)
