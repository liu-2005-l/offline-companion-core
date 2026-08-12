"""语义负反馈：以关键词规则识别用户对提醒的反馈。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from offline_companion.shared.types import FeedbackLevel

_STRONG_NEGATIVE_PATTERNS = (
    r"别再提醒",
    r"不要再提醒",
    r"别提醒我",
    r"关掉提醒",
    r"不要这个提醒",
    r"烦死了",
    r"别烦我",
    r"安静点",
    r"我不想看到",
    r"取消提醒",
)
_WEAK_NEGATIVE_PATTERNS = (
    r"知道了",
    r"行吧",
    r"嗯",
    r"好吧",
    r"先不用",
    r"不用了",
    r"随便",
    r"再说吧",
    r"以后再说",
)
_POSITIVE_PATTERNS = (r"谢谢提醒", r"好的我会", r"收到", r"好的谢谢", r"有用的", r"继续提醒")


@dataclass(frozen=True)
class SemanticFeedbackResult:
    """摘要：提醒反馈的规则分析结果。"""

    level: str | None
    matched_pattern: str | None = None
    confidence: float = 0.0


def analyze_feedback(user_reply: str) -> SemanticFeedbackResult:
    """摘要：按强负面、正面、弱负面的优先级分析用户回复。"""
    text = (user_reply or "").strip().lower()
    if not text:
        return SemanticFeedbackResult(level=None)
    matches = (
        (_STRONG_NEGATIVE_PATTERNS, FeedbackLevel.STRONG_NEGATIVE.value, 0.8),
        (_POSITIVE_PATTERNS, FeedbackLevel.POSITIVE.value, 0.7),
        (_WEAK_NEGATIVE_PATTERNS, FeedbackLevel.WEAK_NEGATIVE.value, 0.6),
    )
    for patterns, level, confidence in matches:
        for pattern in patterns:
            if re.search(pattern, text):
                return SemanticFeedbackResult(level=level, matched_pattern=pattern, confidence=confidence)
    return SemanticFeedbackResult(level=None)
