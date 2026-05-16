"""classifier：规则/词典安全分级器（B3）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .fixed_replies import SafetyRepliesBundle, ensure_safety_replies_loaded, load_safety_replies


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


def classify_user_text(text: str, *, replies_path: Path | None = None) -> SafetyResult:
    """摘要：对用户输入做关键词分级并返回 YAML 中的固定话术（如命中）。

    参数：
        text: 用户输入。
        replies_path: 可选，覆盖默认 ``configs/safety_replies/zh_v1.yaml``。

    返回值：
        ``SafetyResult``；命中危机层级时 ``block_model`` 为 True。
    """
    bundle = (
        load_safety_replies(replies_path)
        if replies_path
        else ensure_safety_replies_loaded()
    )
    return _classify_with_bundle(text, bundle)


def _classify_with_bundle(text: str, bundle: SafetyRepliesBundle) -> SafetyResult:
    t = text.lower()
    for m in bundle.self_markers:
        if m.lower() in t or m in text:
            return SafetyResult(
                tier=SafetyTier.CRISIS_SELF,
                user_visible_reply=bundle.self_reply,
                block_model=True,
            )
    for m in bundle.other_markers:
        if m.lower() in t or m in text:
            return SafetyResult(
                tier=SafetyTier.CRISIS_OTHER,
                user_visible_reply=bundle.other_reply,
                block_model=True,
            )
    return SafetyResult(tier=SafetyTier.OK, user_visible_reply=None, block_model=False)
