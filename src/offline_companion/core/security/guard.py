"""安全 Guard 链与默认 fail-closed 工具策略。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Decision = Literal["allow", "deny", "ask"]
Guard = Callable[["ToolCallContext"], str | None]

logger = logging.getLogger(__name__)

DEFAULT_POLICY: dict[str, Decision] = {
    "read_file": "allow",
    "list_dir": "allow",
    "write_file": "ask",
    "execute_cmd": "ask",
    "network_request": "deny",
}


@dataclass(frozen=True)
class ToolCallContext:
    """摘要：Guard 评估一次工具调用所需的最小上下文。"""

    tool_id: str
    operation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class GuardChain:
    """摘要：只允许增加限制、不能撤销既有拒绝的 Guard 链。"""

    def __init__(self) -> None:
        self._guards: list[Guard] = []

    def add(self, guard: Guard) -> Callable[[], None]:
        """摘要：添加 Guard 并返回幂等释放器。"""
        self._guards.append(guard)
        released = False

        def dispose() -> None:
            nonlocal released
            if released:
                return
            released = True
            if guard in self._guards:
                self._guards.remove(guard)

        return dispose

    def evaluate(self, context: ToolCallContext) -> Decision:
        """摘要：评估所有 Guard，拒绝结果不可被后续 Guard 推翻。"""
        decision: Decision = "allow"
        for guard in tuple(self._guards):
            try:
                reason = guard(context)
            except Exception:
                logger.exception("Guard 执行失败，按 fail-closed 拒绝工具调用")
                decision = "deny"
                continue
            if reason is not None:
                decision = "deny"
        return decision

    def evaluate_tool(self, context: ToolCallContext) -> Decision:
        """摘要：先应用默认工具策略，再应用动态 Guard。"""
        policy_decision = DEFAULT_POLICY.get(context.tool_id, "deny")
        guard_decision = self.evaluate(context)
        if policy_decision == "deny" or guard_decision == "deny":
            return "deny"
        if policy_decision == "ask":
            return "ask"
        return guard_decision
