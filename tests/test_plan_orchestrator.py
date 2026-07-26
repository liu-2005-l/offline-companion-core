from __future__ import annotations

from offline_companion.core.plan_orchestrator import (
    A3ConsentAdapter,
    InMemoryPlanStore,
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
    StepStatus,
    TaskContext,
)


def test_task_context_from_v1_snapshot_keeps_old_data() -> None:
    payload = {
        "plan_id": "p1",
        "status": "paused",
        "steps": {
            "s1": {
                "step_id": "s1",
                "skill_id": "skill-a",
                "result_key": "result_a",
                "depends_on": [],
                "retry_max": 0,
                "retry_backoff_s": 0.0,
                "degrade_value": None,
                "require_consent": False,
                "idempotency_key": None,
                "payload": {"x": 1},
                "fail_fast": True,
                "condition_key": None,
            }
        },
        "step_status": {"s1": "done"},
        "step_results": {"result_a": 123},
        "step_errors": {},
        "step_attempts": {"s1": 1},
        "processed_steps": ["s1"],
        "published_step_events": [],
        "trace_id": "trace-1",
        "context_vars": {"foo": "bar"},
        "error": None,
        "paused_reason": "waiting_consent",
        "paused_step_id": "s1",
    }

    context = TaskContext.from_snapshot(payload)

    assert context.snapshot_version == 2
    assert context.plan_id == "p1"
    assert context.step_results["result_a"] == 123
    assert context.context_vars["foo"] == "bar"
    assert context.started_at is None
    assert context.updated_at is None
    assert context.completed_at is None
    assert context.step_started_at == {}
    assert context.step_completed_at == {}
    assert context.step_consent_requests == {}
    assert context.step_route_decisions == {}


def test_plan_timestamps_refresh_on_start_and_completion() -> None:
    store = InMemoryPlanStore()
    step = PlanStep(step_id="a", skill_id="skill-a", result_key="result_a")
    orchestrator = PlanOrchestrator(store, skill_invoker=lambda skill_id, payload, idem: "ok")

    context = orchestrator.start("plan-ok", [step])

    assert context.status is PlanStatus.DONE
    assert context.started_at is not None
    assert context.updated_at is not None
    assert context.completed_at is not None
    assert context.step_started_at["a"] <= context.step_completed_at["a"]
    assert context.completed_at >= context.started_at


def test_resume_with_denied_consent_marks_cancelled_and_timestamps() -> None:
    store = InMemoryPlanStore()
    step = PlanStep(step_id="a", skill_id="skill-a", result_key="result_a", require_consent=True)
    orchestrator = PlanOrchestrator(store, skill_invoker=lambda skill_id, payload, idem: "ok")

    paused = orchestrator.start("plan-consent", [step])
    assert paused.status is PlanStatus.PAUSED
    assert paused.paused_step_id == "a"
    assert paused.updated_at is not None

    resumed = orchestrator.resume("plan-consent", consent_granted=False)

    assert resumed.status is PlanStatus.CANCELLED
    assert resumed.completed_at is not None
    assert resumed.step_completed_at["a"] <= resumed.completed_at
    assert resumed.step_status["a"] is StepStatus.CANCELLED


def test_cancel_marks_non_terminal_steps_completed_at() -> None:
    store = InMemoryPlanStore()
    orchestrator = PlanOrchestrator(store)
    context = TaskContext(
        plan_id="plan-cancel",
        steps={"a": PlanStep(step_id="a", skill_id="skill-a", result_key="result_a")},
        step_status={"a": StepStatus.PENDING},
    )
    store.save("plan-cancel", context)

    orchestrator.cancel("plan-cancel")
    cancelled = store.load("plan-cancel")

    assert cancelled is not None
    assert cancelled.status is PlanStatus.CANCELLED
    assert cancelled.completed_at is not None
    assert cancelled.step_completed_at["a"] <= cancelled.completed_at


def test_task_context_thin_api_updates_updated_at() -> None:
    step = PlanStep(step_id="a", skill_id="skill-a", result_key="result_a")
    context = TaskContext(plan_id="p2", steps={"a": step}, step_status={"a": StepStatus.PENDING})

    assert context.updated_at is None
    context.set_context_var("route_mode", "cloud")
    first_update = context.updated_at
    assert first_update is not None

    context.set_step_result("a", {"ok": True})
    assert context.get_step_result("a") == {"ok": True}
    assert context.get_context_var("result_a") == {"ok": True}
    assert context.updated_at is not None
    assert context.updated_at >= first_update


def test_resume_reads_consent_from_step_consent_requests_first() -> None:
    store = InMemoryPlanStore()
    step = PlanStep(step_id="a", skill_id="skill-a", result_key="result_a", require_consent=True)
    orchestrator = PlanOrchestrator(store, skill_invoker=lambda skill_id, payload, idem: "ok")

    paused = orchestrator.start("plan-read-structured-consent", [step])
    assert paused.status is PlanStatus.PAUSED
    assert paused.paused_step_id == "a"

    snapshot = store.load("plan-read-structured-consent")
    assert snapshot is not None
    structured = dict(snapshot.step_consent_requests["a"])
    snapshot.context_vars.pop("consent_request", None)
    store.save("plan-read-structured-consent", snapshot)

    resumed = orchestrator.resume("plan-read-structured-consent", consent_granted=True)

    assert resumed.status is PlanStatus.DONE
    assert resumed.get_step_consent_request("a") == structured


def test_consent_adapter_uses_structured_step_request_when_legacy_missing() -> None:
    class _Gateway:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def submit(self, consent_request) -> bool:
            self.requests.append(consent_request)
            return False

    gateway = _Gateway()
    store = InMemoryPlanStore()
    step = PlanStep(step_id="a", skill_id="skill-a", result_key="result_a", require_consent=True)
    orchestrator = PlanOrchestrator(
        store,
        skill_invoker=lambda skill_id, payload, idem: "ok",
        consent_adapter=A3ConsentAdapter(gateway),
    )

    paused = orchestrator.start("plan-adapter-structured-consent", [step])
    assert paused.status is PlanStatus.PAUSED
    snapshot = store.load("plan-adapter-structured-consent")
    assert snapshot is not None
    assert snapshot.step_consent_requests["a"]["step_id"] == "a"
    snapshot.context_vars.pop("consent_request", None)
    store.save("plan-adapter-structured-consent", snapshot)

    resumed = orchestrator.resume("plan-adapter-structured-consent")

    assert resumed.status is PlanStatus.PAUSED
    assert gateway.requests
    assert gateway.requests[-1].step_id == "a"


def test_fallback_chain_advances_after_failure() -> None:
    store = InMemoryPlanStore()
    step = PlanStep(step_id="a", skill_id="skill-x", result_key="res", fail_fast=True)
    orchestrator = PlanOrchestrator(
        store,
        skill_invoker=lambda skill_id, payload, idem: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    ctx = orchestrator.create_context("plan-1")
    ctx.steps = {"a": step}
    ctx.step_status = {"a": StepStatus.PENDING}
    ctx.context_vars["fallback_chain"] = ["local", "cloud", "echo"]

    result = orchestrator.execute_plan("plan-1", context=ctx)

    assert result.status in {PlanStatus.FAILED, PlanStatus.DONE, PlanStatus.RUNNING}
    assert result.context_vars["fallback_index"] >= 0
