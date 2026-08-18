"""UI 标注文本的安全等级检测。"""

from __future__ import annotations

HARD_DANGER_KEYWORDS = ("删除", "清空", "注销", "卸载", "解散", "重置", "格式化")
SOFT_CAUTION_KEYWORDS = ("退出", "关闭", "移除")


def detect_danger(target_text: str) -> str:
    """摘要：检测标注文本的最低危险等级。"""
    text = str(target_text or "")
    if any(keyword in text for keyword in HARD_DANGER_KEYWORDS):
        return "hard"
    if any(keyword in text for keyword in SOFT_CAUTION_KEYWORDS):
        return "soft"
    return "none"
