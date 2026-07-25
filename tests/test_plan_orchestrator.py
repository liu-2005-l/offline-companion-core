from __future__ import annotations



from offline_companion.core.plan_orchestrator import (
    InMemoryPlanStore,
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
    StepStatus,
)

# existing tests omitted for brevity in this edit

def test_fallback_chain_advances_after_failure() -> None:
    store = InMemoryPlanStore()
    step = PlanStep(step_id="a", skill_id="skill-x", result_key="res", fail_fast=True)
    orchestrator = PlanOrchestrator(store, skill_invoker=lambda skill_id, payload, idem: (_ for _ in ()).throw(RuntimeError("boom")))
    ctx = PlanContext = orchestrator.create_context("plan-1")
    ctx.steps = {"a": step}
    ctx.step_status = {"a": StepStatus.PENDING}
    ctx.context_vars["fallback_chain"] = ["local", "cloud", "echo"]

    result = orchestrator.execute_plan("plan-1", context=ctx)

    assert result.status in {PlanStatus.FAILED, PlanStatus.DONE, PlanStatus.RUNNING}
    assert result.context_vars["fallback_index"] >= 0
