"""fallback_controller：管理路由降级状态与历史。"""

from __future__ import annotations

from dataclasses import dataclass

from offline_companion.core.plan_orchestrator import StepStatus, TaskContext
from offline_companion.shared.types import RoutingMode


@dataclass
class FallbackController:
    """摘要：推进 fallback_chain，并记录路由降级历史。"""

    def initialize(self, context: TaskContext, fallback_chain: list[str] | list[RoutingMode], *, route_mode: str | RoutingMode | None = None) -> None:
        chain = [mode.value if isinstance(mode, RoutingMode) else str(mode) for mode in fallback_chain]
        context.context_vars["fallback_chain"] = chain
        context.context_vars["fallback_index"] = 0
        if route_mode is not None:
            context.context_vars["route_mode"] = route_mode.value if isinstance(route_mode, RoutingMode) else str(route_mode)
        elif chain:
            context.context_vars["route_mode"] = chain[0]
        context.context_vars.setdefault("fallback_history", [])

    def can_advance(self, context: TaskContext) -> bool:
        chain = list(context.context_vars.get("fallback_chain") or [])
        index = int(context.context_vars.get("fallback_index", 0) or 0)
        return bool(chain) and index + 1 < len(chain)

    def advance(self, context: TaskContext, *, reason: str, step_id: str | None = None, error: str | None = None) -> bool:
        if not self.can_advance(context):
            return False
        chain = list(context.context_vars.get("fallback_chain") or [])
        index = int(context.context_vars.get("fallback_index", 0) or 0)
        current_mode = chain[index]
        next_mode = chain[index + 1]
        history = list(context.context_vars.get("fallback_history") or [])
        history.append(
            {
                "from": current_mode,
                "to": next_mode,
                "reason": reason,
                "step_id": step_id,
                "error": error,
            }
        )
        context.context_vars["fallback_history"] = history
        context.context_vars["fallback_index"] = index + 1
        context.context_vars["route_mode"] = next_mode
        context.context_vars["route_reason"] = reason
        if step_id is not None and step_id in context.step_status:
            context.step_status[step_id] = StepStatus.PENDING
            context.step_errors.pop(step_id, None)
            if step_id not in context.processed_steps:
                context.processed_steps.append(step_id)
        return True
