"""abstract_ui：UI 宿主抽象接口（A1）。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class UIHost(Protocol):
    """摘要：宿主 UI 的最小契约（终端/GUI/Web 均可实现）。"""

    def show_message(self, role: str, text: str) -> None:
        """摘要：展示一条对话或系统消息。"""
        ...
