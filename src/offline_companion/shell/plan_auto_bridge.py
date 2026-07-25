"""plan_auto_bridge：将 AutoRouter 与 PlanOrchestrator 连接起来的 A2 桥接层。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from offline_companion.core.fallback_controller import FallbackController
from offline_companion.core.plan_orchestrator import PlanContext, PlanOrchestrator, PlanStep
from offline_companion.shell.auto_router import AutoRouter, AutoRoutingAdapter, RoutingContext, RoutingDecision, RoutingMode
from offline_companion.shared.messages import BaseMessage

PlanInvokeSkill = Callable[[Any, PlanContext], Any]


@dataclass
class PlanAutoBridge:
    """摘要：先做自动路由，再按路由结果触发计划执行。"""

    auto_router: AutoRouter
    plan_orchestrator: PlanOrchestrator
    context_factory: Callable[[BaseMessage], RoutingContext]
    fallback_controller: FallbackController = field(default_factory=FallbackController)

    def decide(self, message: BaseMessage) -> RoutingDecision:
        adapter = AutoRoutingAdapter(self.auto_router, self.context_factory)
        return adapter.route(message)

    def execute(
        self,
        message: BaseMessage,
        *,
        plan_id: str,
        invoke_skill: PlanInvokeSkill,
        context: PlanContext | None = None,
    ) -> PlanContext:
        decision = self.decide(message)
        routed_context = context or self.plan_orchestrator.create_context(plan_id)
        route_decision = {
            "mode": decision.mode.value,
            "reason": decision.reason,
            "confidence": decision.confidence,
            "policy_blocked": decision.policy_blocked,
            "requires_consent": decision.requires_consent,
            "fallback_chain": [mode.value for mode in decision.fallback_chain],
            "selected_by": decision.selected_by,
        }
        routed_context.state["route_decision"] = route_decision
        state_manager = getattr(getattr(self.plan_orchestrator, "_store", None), "_state_manager", None)
        if state_manager is not None and hasattr(state_manager, "set_route_state"):
            state_manager.set_route_state(plan_id, route_decision)
        routed_context.state["auto_route"] = decision.mode.value
        routed_context.state["auto_route_reason"] = decision.reason
        routed_context.state["requires_consent"] = decision.requires_consent
        routed_context.state["fallback_chain"] = [mode.value for mode in decision.fallback_chain]
        self.fallback_controller.initialize(routed_context, [mode.value for mode in decision.fallback_chain], route_mode=decision.mode)
        if not routed_context.steps:
            try:
                template_steps = self.plan_orchestrator.load_template(plan_id)
                routed_context.steps = {step.step_id: step for step in template_steps}
                routed_context.step_status = {step.step_id: self.plan_orchestrator._default_step_status(step.step_id) for step in template_steps}  # type: ignore[attr-defined]
            except Exception:
                pass
        if decision.requires_consent and routed_context.steps:
            first_step_id = next(iter(routed_context.steps))
            first_step = routed_context.steps[first_step_id]
            if not first_step.require_consent:
                routed_context.steps[first_step_id] = PlanStep(**{**asdict(first_step), "require_consent": True})
        if decision.mode == RoutingMode.ECHO:
            routed_context.state["plan_routed"] = "echo"
            routed_context.state["status"] = routed_context.status.value
            return routed_context
        result = self.plan_orchestrator.execute_plan(
            plan_id,
            invoke_skill=invoke_skill,
            context=routed_context,
        )
        result.state["status"] = result.status.value
        result.state["plan_routed"] = result.state.get("plan_routed", decision.mode.value)
        return result
