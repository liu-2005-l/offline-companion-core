"""Consent asked/decided 审计对。"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from offline_companion.core.event_stream.stream import EventStream

_VALID_OUTCOMES = frozenset({"allowed-once", "rejected", "cancelled", "unavailable"})


class ApprovalAuditPair:
    """摘要：强制每个审批请求写入完整的 asked + decided 审计对。"""

    def __init__(self, event_stream: EventStream) -> None:
        self._event_stream = event_stream
        self._asked: set[str] = set()

    def asked(self, call_id: str, tool_name: str, reason: str | None = None) -> str:
        """摘要：记录审批请求并返回 approval ID。"""
        approval_id = uuid4().hex
        self._event_stream.append(
            "consent/asked",
            {
                "approval_id": approval_id,
                "call_id": call_id,
                "tool_name": tool_name,
                "reason": reason,
            },
        )
        self._asked.add(approval_id)
        return approval_id

    def decided(self, approval_id: str, outcome: str) -> None:
        """摘要：记录审批决定，未匹配 asked 或结果非法时拒绝写入。"""
        if approval_id not in self._asked:
            raise ValueError(f"未找到对应的审批请求: {approval_id}")
        if outcome not in _VALID_OUTCOMES:
            raise ValueError(f"非法审批结果: {outcome}")
        self._event_stream.append(
            "consent/decided",
            {"approval_id": approval_id, "outcome": outcome},
        )
        self._asked.remove(approval_id)

    def execute_pair(
        self,
        call_id: str,
        tool_name: str,
        reason: str | None,
        decision_fn: Callable[[], str],
    ) -> str:
        """摘要：执行完整审批对，任一审计写入失败均向调用方抛错。"""
        approval_id = self.asked(call_id, tool_name, reason)
        decision = decision_fn()
        outcome = {
            "allow": "allowed-once",
            "deny": "rejected",
            "ask": "cancelled",
        }.get(decision)
        if outcome is None:
            raise ValueError(f"非法审批决策: {decision}")
        self.decided(approval_id, outcome)
        return decision
