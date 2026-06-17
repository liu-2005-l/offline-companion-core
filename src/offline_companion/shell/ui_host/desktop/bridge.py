"""bridge：pywebview JS ↔ Python API（进程内编排，不经 HTTP）。"""

from __future__ import annotations

import threading
from typing import Any

from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shell.ui_host.turn_payload import process_chat_message


class DesktopBridge:
    """摘要：暴露给前端 ``pywebview.api`` 的 Python 方法集。"""

    def __init__(self, runtime: DesktopRuntime) -> None:
        self._runtime = runtime
        # pywebview 在 WebView 线程回调；与主线程共用 SQLite 连接须串行化
        self._turn_lock = threading.Lock()

    def run_turn(self, message: str) -> dict[str, Any]:
        """摘要：处理用户消息并返回回复载荷。"""
        with self._turn_lock:
            return process_chat_message(self._runtime, message)

    def get_status(self) -> dict[str, Any]:
        """摘要：底栏与侧栏所需的会话状态。"""
        return {
            "memory_on": self._runtime.memory_on,
            "session_id": self._runtime.session_id,
            "persona_name": self._runtime.persona_name,
            "privacy_mode": self._runtime.privacy_mode.value,
            "model_label": self._runtime.model_label,
        }

    def set_memory(self, enabled: bool) -> dict[str, Any]:
        """摘要：切换记忆开关。"""
        self._runtime.memory_on = bool(enabled)
        return {"memory_on": self._runtime.memory_on}

    def consent_placeholder(self) -> dict[str, Any]:
        """摘要：Consent 模态槽位（Sprint 7.2 接入真实出站同意）。"""
        return {
            "title": "出站同意（占位）",
            "body": "Sprint 7.2 将在此展示 Consent Artifact 详情并收集用户决定。",
            "purpose_type": "skill_cloud_call",
        }
