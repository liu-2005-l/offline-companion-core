"""摘要：pywebview 进程内桥接，负责对话与同意恢复。"""

from __future__ import annotations

import threading
from typing import Any

from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shell.ui_host.turn_payload import (
    process_chat_message,
    turn_result_to_payload,
)


class DesktopBridge:
    """摘要：暴露给 `pywebview.api` 的 Python 方法集合。"""

    def __init__(self, runtime: DesktopRuntime) -> None:
        self._runtime = runtime
        self._turn_lock = threading.Lock()

    def run_turn(self, message: str) -> dict[str, Any]:
        """摘要：处理用户消息并返回回复载荷。"""
        with self._turn_lock:
            return process_chat_message(self._runtime, message)

    def get_status(self) -> dict[str, Any]:
        """摘要：返回底栏与侧栏需要的会话状态。"""
        status = {
            "memory_on": self._runtime.memory_on,
            "session_id": self._runtime.session_id,
            "persona_name": self._runtime.persona_name,
            "privacy_mode": self._runtime.privacy_mode.value,
            "model_label": self._runtime.model_label,
        }
        state_manager = getattr(getattr(self._runtime.orchestrator, "_store", None), "_state_manager", None)
        if state_manager is not None:
            status["route_state"] = state_manager.get_route_state(self._runtime.session_id, default={})
            status["task_state"] = state_manager.get_task_state(f"plan.{self._runtime.session_id}.snapshot", default={})
        return status

    def set_memory(self, enabled: bool) -> dict[str, Any]:
        """摘要：切换记忆开关。"""
        self._runtime.memory_on = bool(enabled)
        return {"memory_on": self._runtime.memory_on}

    def consent_placeholder(self) -> dict[str, Any]:
        """摘要：返回当前待处理的同意弹窗数据。"""
        gateway = getattr(self._runtime.orchestrator, "consent_gateway", None)
        if isinstance(gateway, UIHostConsentGateway):
            return gateway.to_modal_payload()
        return {
            "title": "出站同意（占位）",
            "body": "当前没有可用的同意网关。",
            "purpose_type": "skill_cloud_inference",
        }

    def consent_decision(self, request_id: str, allowed: bool) -> dict[str, Any]:
        """摘要：提交单轮同意决策，并在允许时恢复执行。"""
        with self._turn_lock:
            result = self._runtime.orchestrator.resume_pending_turn(request_id, allowed=allowed)
            return turn_result_to_payload(result)
