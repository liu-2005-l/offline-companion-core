"""memory_store：记忆待确认、确认提交与写入编排。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .decision_engine import MemoryDecision, MemoryDecisionEngine


@dataclass
class MemoryStoreController:
    """摘要：把记忆决策落到可执行的写入/澄清动作。"""

    decision_engine: MemoryDecisionEngine = field(default_factory=MemoryDecisionEngine)
    _pending: dict[str, dict[str, Any]] = field(default_factory=dict)

    def has_pending(self) -> bool:
        return bool(self._pending)

    def pending_ids(self) -> list[str]:
        return list(self._pending.keys())

    def bind(self, conn, session_id: str) -> None:
        self.conn = conn
        self.session_id = session_id

    def handle_input(self, user_text: str) -> dict[str, Any]:
        decision = self.decision_engine.decide(user_text)
        if decision.route == "clarify" and decision.candidate is not None:
            pending_id = f"pending:{len(self._pending) + 1}"
            self._pending[pending_id] = {
                "candidate": decision.candidate,
                "decision": decision,
                "text": user_text,
            }
            return {
                "action": "clarify",
                "pending_id": pending_id,
                "reply": decision.confirm_prompt,
            }
        if decision.route == "memory" and decision.memory_item is not None:
            return {
                "action": "write",
                "memory_item": decision.memory_item,
            }
        return {"action": "chat"}

    def confirm_pending(self, pending_id: str) -> dict[str, Any]:
        pending = self._pending.pop(pending_id, None)
        if pending is None:
            return {"action": "missing"}
        decision: MemoryDecision = pending["decision"]
        if decision.memory_item is None:
            return {"action": "missing"}
        return {"action": "write", "memory_item": decision.memory_item}
