"""plan_auto_bridge：将 AutoRouter 与 PlanOrchestrator 连接起来的 A2 桥接层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from offline_companion.core.plan_orchestrator import PlanContext, PlanOrchestrator
from offline_companion.shell.auto_router import AutoRouter, AutoRoutingAdapter, RoutingContext, RoutingDecision, RoutingMode
from offline_companion.shared.messages import BaseMessage

PlanInvokeSkill = Callable[[Any, PlanContext], Any]


@dataclass
class PlanAutoBridge:
    """摘要：先做自动路由，再按路由结果触发计划执行。"""

    auto_router: AutoRouter
    plan_orchestrator: PlanOrchestrator
    context_factory: Callable[[BaseMessage], RoutingContext]

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
        routed_context.state["auto_route"] = decision.mode.value
        routed_context.state["auto_route_reason"] = decision.reason
        if decision.mode == RoutingMode.ECHO:
            routed_context.state["plan_routed"] = "echo"
            return routed_context
        return self.plan_orchestrator.execute_plan(
            plan_id,
            invoke_skill=invoke_skill,
            context=routed_context,
        )
