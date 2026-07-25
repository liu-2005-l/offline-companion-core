from __future__ import annotations

from offline_companion.core.fallback_controller import FallbackController
from offline_companion.core.plan_orchestrator import PlanContext, PlanStep, StepStatus


def test_fallback_controller_advances_and_records_history() -> None:
    ctx = PlanContext(plan_id="p1", steps={"s1": PlanStep(step_id="s1", skill_id="k", result_key="r")}, step_status={"s1": StepStatus.FAILED})
    ctl = FallbackController()
    ctl.initialize(ctx, ["local", "cloud", "echo"], route_mode="local")

    assert ctl.can_advance(ctx) is True
    assert ctl.advance(ctx, reason="boom", step_id="s1", error="boom") is True
    assert ctx.context_vars["route_mode"] == "cloud"
    assert ctx.context_vars["fallback_index"] == 1
    assert ctx.context_vars["fallback_history"][0]["from"] == "local"
    assert ctx.step_status["s1"] is StepStatus.PENDING
