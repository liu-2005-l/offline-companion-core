"""ToolRegistry 专用控制流错误。"""

from __future__ import annotations


class ToolBlockedError(RuntimeError):
    """摘要：本地流程门禁拒绝 Tool 执行，并携带结构化阻断信息。"""

    def __init__(self, message: str, *, data: dict[str, object]) -> None:
        super().__init__(message)
        self.data = data
