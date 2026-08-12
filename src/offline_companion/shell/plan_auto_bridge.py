"""plan_auto_bridge：将 AutoRouter 与 PlanOrchestrator 连接起来的 A2 桥接层。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from offline_companion.core.fallback_controller import FallbackController
from offline_companion.core.plan_orchestrator import PlanContext, PlanOrchestrator, PlanStep
from offline_companion.shared.messages import BaseMessage
from offline_companion.shared.types import PrivacyMode
from offline_companion.shell.auto_router import (
    AutoRouter,
    AutoRoutingAdapter,
    RoutingContext,
    RoutingDecision,
    RoutingMode,
)

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
        """摘要：兼容入口，依次完成路由准备与计划执行。"""
        routed_context = self.prepare(message, plan_id=plan_id, context=context)
        return self.execute_routed(
            plan_id=plan_id,
            invoke_skill=invoke_skill,
            context=routed_context,
        )

    def prepare(
        self,
        message: BaseMessage,
        *,
        plan_id: str,
        context: PlanContext | None = None,
    ) -> PlanContext:
        """摘要：加载计划并持久化逐步骤路由决策，但不执行步骤。"""
        routed_context = context or self.plan_orchestrator.create_context(plan_id)
        if not routed_context.steps:
            try:
                template_steps = self.plan_orchestrator.load_template(plan_id)
                routed_context.steps = {step.step_id: step for step in template_steps}
                routed_context.step_status = {step.step_id: self.plan_orchestrator._default_step_status(step.step_id) for step in template_steps}  # type: ignore[attr-defined]
            except Exception:
                pass
        decisions = self._route_steps(message, routed_context)
        first_decision = next(iter(decisions.values()), self.decide(message))
        first_payload = routed_context.get_step_route_decision(next(iter(decisions), "")) or self._decision_payload(first_decision)
        routed_context.state["auto_route"] = first_decision.mode.value
        routed_context.state["auto_route_reason"] = first_decision.reason
        routed_context.state["requires_consent"] = any(item.requires_consent for item in decisions.values())
        routed_context.state["fallback_chain"] = list(first_payload.get("fallback_chain") or [])
        self.fallback_controller.initialize(
            routed_context,
            list(first_payload.get("fallback_chain") or []),
            route_mode=first_decision.mode,
        )
        state_manager = getattr(getattr(self.plan_orchestrator, "_store", None), "_state_manager", None)
        if state_manager is not None and hasattr(state_manager, "set_route_state"):
            state_manager.set_route_state(plan_id, first_payload)
        if decisions and all(item.mode == RoutingMode.ECHO for item in decisions.values()):
            routed_context.state["plan_routed"] = "echo"
            routed_context.state["status"] = routed_context.status.value
        return routed_context

    def execute_routed(
        self,
        *,
        plan_id: str,
        invoke_skill: PlanInvokeSkill,
        context: PlanContext,
    ) -> PlanContext:
        """摘要：执行已完成逐步骤路由的计划上下文。"""
        if context.state.get("plan_routed") == "echo":
            return context
        result = self.plan_orchestrator.execute_plan(
            plan_id,
            invoke_skill=invoke_skill,
            context=context,
        )
        result.state["status"] = result.status.value
        result.state["plan_routed"] = result.state.get(
            "plan_routed",
            context.state.get("auto_route", RoutingMode.LOCAL.value),
        )
        return result

    def _route_steps(self, message: BaseMessage, context: PlanContext) -> dict[str, RoutingDecision]:
        """摘要：为计划中的每个步骤生成并持久化独立路由决策。"""
        base_context = self.context_factory(message)
        decisions: dict[str, RoutingDecision] = {}
        for step_id, step in context.steps.items():
            query = str(step.payload.get("description") or step.payload.get("query") or "").strip()
            if not query:
                query = f"{step.skill_id} {json.dumps(step.payload, ensure_ascii=False, sort_keys=True)}".strip()
            metadata = {
                **base_context.metadata,
                "step_id": step_id,
                "skill_id": step.skill_id,
                "requires_consent": bool(base_context.metadata.get("requires_consent")) or step.require_consent,
            }
            complexity = int(step.payload.get("complexity", base_context.complexity) or 0)
            step_context = replace(base_context, query=query, complexity=complexity, metadata=metadata)
            decision = self.auto_router.decide(step_context)
            if decision.mode == RoutingMode.CLOUD and base_context.privacy_mode != PrivacyMode.AUTO_ROUTE_CLOUD.value:
                decision = replace(decision, requires_consent=True)
            decisions[step_id] = decision
            context.set_step_route_decision(step_id, self._decision_payload(decision))
            if decision.requires_consent and not step.require_consent:
                context.steps[step_id] = PlanStep(**{**asdict(step), "require_consent": True})
        return decisions

    @staticmethod
    def _decision_payload(decision: RoutingDecision) -> dict[str, Any]:
        """摘要：将路由决策转换为可持久化字典。"""
        return {
            "mode": decision.mode.value,
            "reason": decision.reason,
            "confidence": decision.confidence,
            "policy_blocked": decision.policy_blocked,
            "requires_consent": decision.requires_consent,
            "fallback_chain": [mode.value for mode in decision.fallback_chain],
            "selected_by": decision.selected_by,
        }
