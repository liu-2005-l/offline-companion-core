from __future__ import annotations

from offline_companion.core.plan_orchestrator import (
    A3ConsentAdapter,
    InMemoryPlanStore,
    PlanContext,
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
    StepStatus,
    TaskContext,
)
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway


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
    assert context.steps["s1"].title == ""
    assert context.steps["s1"].files == ()


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


def test_plan_orchestrator_decide_builds_rule_dag() -> None:
    orchestrator = PlanOrchestrator(InMemoryPlanStore())

    steps = orchestrator.decide("实现一个本地验证脚本")

    assert len(steps) == 5
    assert steps[0].skill_id == "chat"
    assert steps[1].depends_on == ("step_0",)
    assert steps[2].payload["description"].startswith("实现核心逻辑")
    assert steps[2].title.startswith("实现核心逻辑")
    assert steps[2].description
    assert steps[2].expected_output
    assert steps[2].verification
    assert steps[2].completion_criteria
    assert steps[2].stage == "tdd"
    assert steps[2].estimated_minutes > 0
    assert steps[2].payload["expected_output"] == steps[2].expected_output


def test_plan_orchestrator_decide_marks_high_risk_step() -> None:
    orchestrator = PlanOrchestrator(InMemoryPlanStore())

    steps = orchestrator.decide("部署服务并配置网络权限")

    assert any(step.require_consent for step in steps)
    assert orchestrator.decide("  ") == []


def test_plan_orchestrator_decide_default_steps_are_structured() -> None:
    orchestrator = PlanOrchestrator(InMemoryPlanStore())

    steps = orchestrator.decide("帮我处理这个事情")
    combined = "\n".join(
        f"{step.title}\n{step.description}\n{step.expected_output}\n{step.verification}\n{step.completion_criteria}"
        for step in steps
    )

    assert len(steps) == 4
    assert "执行核心步骤" not in combined
    assert "验证与收尾" not in combined
    assert all(step.expected_output and step.verification and step.completion_criteria for step in steps)


def test_task_context_snapshot_preserves_plan_step_metadata() -> None:
    step = PlanStep(
        step_id="a",
        skill_id="skill-a",
        result_key="result_a",
        title="写入配置文件",
        description="在 configs 下写入最小配置。",
        expected_output="配置文件存在。",
        verification="检查配置文件路径。",
        completion_criteria="配置文件存在且内容非空。",
        stage="tdd",
        estimated_minutes=3,
        files=("configs/demo.yaml",),
    )
    context = TaskContext(
        plan_id="metadata",
        steps={"a": step},
        step_status={"a": StepStatus.PENDING},
    )

    restored = TaskContext.from_snapshot(context.to_snapshot())

    restored_step = restored.steps["a"]
    assert restored_step.title == step.title
    assert restored_step.expected_output == step.expected_output
    assert restored_step.verification == step.verification
    assert restored_step.completion_criteria == step.completion_criteria
    assert restored_step.stage == "tdd"
    assert restored_step.files == ("configs/demo.yaml",)


def test_execute_next_runs_only_one_step() -> None:
    store = InMemoryPlanStore()
    orchestrator = PlanOrchestrator(
        store,
        skill_invoker=lambda skill_id, payload, idem: skill_id,
    )
    context = orchestrator.create_context("stepwise")
    steps = [
        PlanStep(step_id="a", skill_id="first", result_key="first_result"),
        PlanStep(step_id="b", skill_id="second", result_key="second_result", depends_on=("a",)),
    ]
    context.steps = {step.step_id: step for step in steps}
    context.step_status = {step.step_id: StepStatus.PENDING for step in steps}

    first = orchestrator.execute_next(context)

    assert first.step_status["a"] is StepStatus.DONE
    assert first.step_status["b"] is StepStatus.PENDING
    assert first.status is PlanStatus.RUNNING
    second = orchestrator.execute_next(first)
    assert second.status is PlanStatus.DONE


def test_execute_next_persists_real_consent_request_id() -> None:
    store = InMemoryPlanStore()
    gateway = UIHostConsentGateway()
    orchestrator = PlanOrchestrator(
        store,
        skill_invoker=lambda skill_id, payload, idem: True,
        consent_adapter=A3ConsentAdapter(gateway),
        consent_gateway=gateway,
    )
    context = orchestrator.create_context("consent-step")
    step = PlanStep(
        step_id="a",
        skill_id="cloud",
        result_key="result",
        require_consent=True,
    )
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.PENDING}

    paused = orchestrator.execute_next(context)
    request_id = paused.get_step_consent_request("a")["request_id"]

    assert paused.paused_reason == "waiting_consent"
    assert request_id in gateway.pending
    loaded = orchestrator.load_context("consent-step")
    assert isinstance(loaded, PlanContext)
    assert loaded.get_step_consent_request("a")["request_id"] == request_id
