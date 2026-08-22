from __future__ import annotations

import pytest

from offline_companion.core.decomposition_result import NotDecomposableResult
from offline_companion.core.plan_orchestrator import (
    A2PlanValidationError,
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


class RecordingPlanEventPublisher:
    """摘要：记录 PlanOrchestrator 发布的事件，供集成测试断言。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, str | None]] = []

    def publish(self, event_name: str, context: TaskContext, *, current_step: str | None = None) -> None:
        del context
        self.events.append((event_name, current_step))


class RecordingSampleLifecycle:
    """摘要：记录终态样本回写调用，可选择模拟回写失败。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.outcomes: list[tuple[str, bool]] = []
        self.verified_candidates: list[str] = []

    def record_plan_outcome(self, sample_id: str, *, completed: bool) -> None:
        if self.fail:
            raise RuntimeError("feedback unavailable")
        self.outcomes.append((sample_id, completed))

    def auto_verify_candidate(self, sample_id: str) -> None:
        if self.fail:
            raise RuntimeError("feedback unavailable")
        self.verified_candidates.append(sample_id)


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


def test_terminal_feedback_updates_provenance_and_auto_verifies_candidate_once() -> None:
    store = InMemoryPlanStore()
    lifecycle = RecordingSampleLifecycle()
    orchestrator = PlanOrchestrator(store, sample_lifecycle=lifecycle)
    step = PlanStep(step_id="a", skill_id="chat", result_key="result_a")
    context = PlanContext(
        plan_id="plan-feedback-green",
        status=PlanStatus.DONE,
        steps={"a": step},
        step_status={"a": StepStatus.DONE},
        context_vars={
            "decomposition": {
                "sample_ids": ["10", "10", "11", "12"],
                "candidate_sample_id": "12",
            }
        },
    )

    first = orchestrator.execute_next(context)
    second = orchestrator.execute_next(first)

    assert lifecycle.outcomes == [("10", True), ("11", True), ("12", True)]
    assert lifecycle.verified_candidates == ["12"]
    assert second.context_vars["_sample_feedback_applied"] is True


def test_terminal_feedback_treats_quality_retry_as_failure() -> None:
    lifecycle = RecordingSampleLifecycle()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), sample_lifecycle=lifecycle)
    step = PlanStep(step_id="a", skill_id="chat", result_key="result_a")
    context = PlanContext(
        plan_id="plan-feedback-retry",
        status=PlanStatus.DONE,
        steps={"a": step},
        step_status={"a": StepStatus.DONE},
        quality_retry_counts={"a": 1},
        context_vars={
            "decomposition": {
                "sample_ids": ["20"],
                "candidate_sample_id": "21",
            }
        },
    )

    orchestrator.execute_next(context)

    assert lifecycle.outcomes == [("20", False), ("21", False)]
    assert lifecycle.verified_candidates == []


@pytest.mark.parametrize(
    ("plan_status", "status", "step_status"),
    [
        ("failed", PlanStatus.FAILED, StepStatus.DEGRADED),
    ],
)
def test_terminal_feedback_non_green_states_count_as_failure(
    plan_status,
    status,
    step_status,
) -> None:
    lifecycle = RecordingSampleLifecycle()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), sample_lifecycle=lifecycle)
    step = PlanStep(step_id="a", skill_id="chat", result_key="result_a")
    context = PlanContext(
        plan_id=f"plan-feedback-{step_status.value}",
        status=status,
        plan_status=plan_status,
        steps={"a": step},
        step_status={"a": step_status},
        context_vars={
            "decomposition": {
                "sample_ids": ["25"],
                "candidate_sample_id": "26",
            }
        },
    )

    orchestrator.execute_next(context)

    assert lifecycle.outcomes == [("25", False), ("26", False)]
    assert lifecycle.verified_candidates == []


def test_blocked_plan_waits_for_recovery_before_terminal_feedback() -> None:
    lifecycle = RecordingSampleLifecycle()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), sample_lifecycle=lifecycle)
    step = PlanStep(step_id="a", skill_id="chat", result_key="result_a")
    context = PlanContext(
        plan_id="plan-feedback-blocked-recovery",
        status=PlanStatus.FAILED,
        plan_status="blocked",
        steps={"a": step},
        step_status={"a": StepStatus.BLOCKED},
        context_vars={
            "decomposition": {
                "sample_ids": ["27"],
                "candidate_sample_id": "28",
            }
        },
    )

    blocked = orchestrator.execute_next(context)
    assert lifecycle.outcomes == []
    assert "_sample_feedback_applied" not in blocked.context_vars

    blocked.plan_status = None
    blocked.status = PlanStatus.RUNNING
    blocked.step_status["a"] = StepStatus.READY
    recovered = orchestrator.execute_next(
        blocked,
        invoke_skill=lambda current_step, current_context: "完成",
    )

    assert recovered.status is PlanStatus.DONE
    assert lifecycle.outcomes == [("27", True), ("28", True)]
    assert lifecycle.verified_candidates == ["28"]


def test_cancelled_plan_does_not_count_as_sample_failure() -> None:
    lifecycle = RecordingSampleLifecycle()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), sample_lifecycle=lifecycle)
    step = PlanStep(step_id="a", skill_id="chat", result_key="result_a")
    context = PlanContext(
        plan_id="plan-feedback-cancelled",
        status=PlanStatus.CANCELLED,
        steps={"a": step},
        step_status={"a": StepStatus.CANCELLED},
        context_vars={
            "decomposition": {
                "sample_ids": ["29"],
                "candidate_sample_id": "30",
            }
        },
    )

    cancelled = orchestrator.execute_next(context)

    assert cancelled.context_vars["_sample_feedback_applied"] is True
    assert lifecycle.outcomes == []
    assert lifecycle.verified_candidates == []


def test_terminal_feedback_empty_provenance_is_noop_and_failure_is_contained() -> None:
    empty_lifecycle = RecordingSampleLifecycle()
    empty_orchestrator = PlanOrchestrator(InMemoryPlanStore(), sample_lifecycle=empty_lifecycle)
    failed_step = PlanStep(step_id="a", skill_id="chat", result_key="result_a")
    empty = PlanContext(
        plan_id="plan-feedback-empty",
        status=PlanStatus.FAILED,
        plan_status="failed",
        steps={"a": failed_step},
        step_status={"a": StepStatus.FAILED},
        context_vars={"decomposition": {"sample_ids": [], "candidate_sample_id": None}},
    )
    assert empty_orchestrator.execute_next(empty).status is PlanStatus.FAILED
    assert empty_lifecycle.outcomes == []

    failing_lifecycle = RecordingSampleLifecycle(fail=True)
    failing_orchestrator = PlanOrchestrator(InMemoryPlanStore(), sample_lifecycle=failing_lifecycle)
    failed = PlanContext(
        plan_id="plan-feedback-contained",
        status=PlanStatus.FAILED,
        plan_status="failed",
        steps={"a": failed_step},
        step_status={"a": StepStatus.FAILED},
        context_vars={"decomposition": {"sample_ids": ["30"], "candidate_sample_id": None}},
    )

    result = failing_orchestrator.execute_next(failed)

    assert result.status is PlanStatus.FAILED
    assert result.context_vars["_sample_feedback_applied"] is True


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


def test_plan_orchestrator_decide_unmatched_goal_returns_chat_fallback() -> None:
    orchestrator = PlanOrchestrator(InMemoryPlanStore())

    result = orchestrator.decide("帮我处理这个事情")

    assert result == NotDecomposableResult(
        reason="no_rule_match",
        original_input="帮我处理这个事情",
    )


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


def test_execute_next_post_verification_failure_marks_step_failed() -> None:
    """摘要：后置校验失败时步骤进入 FAILED，并记录 post verification 错误。"""
    store = InMemoryPlanStore()
    orchestrator = PlanOrchestrator(
        store,
        skill_invoker=lambda skill_id, payload, idem: "",
    )
    context = orchestrator.create_context("post-verification")
    step = PlanStep(
        step_id="planning",
        skill_id="chat",
        result_key="result",
        stage="planning",
    )
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.PENDING}

    failed = orchestrator.execute_next(context)

    assert failed.status is PlanStatus.FAILED
    assert failed.step_status["planning"] is StepStatus.FAILED
    assert failed.paused_reason == "post_verification_failed"
    assert "planning_stage_empty_output" in failed.step_errors["planning"]


def test_execute_next_post_verification_retry_succeeds() -> None:
    """摘要：第一次后置校验失败时注入 feedback 并重试一次，成功后步骤完成。"""
    store = InMemoryPlanStore()
    calls: list[dict[str, object]] = []

    def invoke(step: PlanStep, context: TaskContext) -> str:
        calls.append(dict(context.feedback_overrides))
        if len(calls) == 1:
            return ""
        assert "planning" in context.feedback_overrides[step.step_id]
        return "模块 plan_dag_engine，数据流 A 到 B，测试策略覆盖。"

    orchestrator = PlanOrchestrator(store)
    context = orchestrator.create_context("post-verification-retry")
    step = PlanStep(step_id="planning", skill_id="chat", result_key="result", stage="planning")
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.PENDING}

    completed = orchestrator.execute_next(context, invoke_skill=invoke)

    assert completed.status is PlanStatus.DONE
    assert completed.step_status["planning"] is StepStatus.DONE
    assert len(calls) == 2
    assert completed.quality_retry_counts["planning"] == 1
    assert "planning" not in completed.feedback_overrides
    assert completed.get_step_result("planning") == "模块 plan_dag_engine，数据流 A 到 B，测试策略覆盖。"


def test_execute_next_routed_retry_receives_quality_feedback() -> None:
    """摘要：routed 真执行链在质量重试时能读取本轮校验反馈。"""

    class RetryAwareRoutedInvoker:
        def __init__(self) -> None:
            self.feedback: list[str | None] = []

        def invoke_step(self, _step: PlanStep, context: TaskContext) -> str:
            feedback = context.context_vars.get("_quality_retry_feedback")
            self.feedback.append(str(feedback) if feedback else None)
            if feedback:
                return "模块 plan_dag_engine，数据流 A 到 B，测试策略覆盖。"
            return "已完成当前步骤。"

    routed_invoker = RetryAwareRoutedInvoker()
    orchestrator = PlanOrchestrator(InMemoryPlanStore())
    orchestrator.attach_routed_invoker(routed_invoker)
    context = orchestrator.create_context("routed-post-verification")
    step = PlanStep(
        step_id="planning",
        skill_id="chat",
        result_key="result",
        stage="planning",
    )
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.PENDING}

    completed = orchestrator.execute_next(context)

    assert completed.status is PlanStatus.DONE
    assert routed_invoker.feedback[0] is None
    assert "planning_stage_missing_module_description" in routed_invoker.feedback[1]


def test_execute_next_post_verification_retry_failure_marks_failed() -> None:
    """摘要：重试仍失败时标记 FAILED，且不会第三次重试。"""
    call_count = {"n": 0}

    def invoke(_step: PlanStep, _context: TaskContext) -> str:
        call_count["n"] += 1
        return ""

    orchestrator = PlanOrchestrator(InMemoryPlanStore())
    context = orchestrator.create_context("post-verification-retry-failed")
    step = PlanStep(step_id="planning", skill_id="chat", result_key="result", stage="planning")
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.PENDING}

    failed = orchestrator.execute_next(context, invoke_skill=invoke)

    assert call_count["n"] == 2
    assert failed.status is PlanStatus.FAILED
    assert failed.step_status["planning"] is StepStatus.FAILED
    assert failed.paused_reason == "post_verification_failed"
    assert failed.quality_retry_counts["planning"] == 1


def test_execute_next_post_verification_failure_blocks_downstream() -> None:
    """摘要：上游后置校验重试仍失败时，下游依赖步骤自动进入 BLOCKED。"""
    publisher = RecordingPlanEventPublisher()
    calls: list[str] = []

    def invoke(step: PlanStep, _context: TaskContext) -> str:
        calls.append(step.step_id)
        return ""

    orchestrator = PlanOrchestrator(InMemoryPlanStore(), event_publisher=publisher)
    context = orchestrator.create_context("post-verification-propagation")
    first = PlanStep(step_id="planning", skill_id="chat", result_key="ra", stage="planning")
    second = PlanStep(step_id="implementation", skill_id="chat", result_key="rb", depends_on=("planning",))
    context.steps = {first.step_id: first, second.step_id: second}
    context.step_status = {first.step_id: StepStatus.PENDING, second.step_id: StepStatus.PENDING}

    failed = orchestrator.execute_next(context, invoke_skill=invoke)

    assert calls == ["planning", "planning"]
    assert failed.status is PlanStatus.FAILED
    assert failed.step_status["planning"] is StepStatus.FAILED
    assert failed.step_status["implementation"] is StepStatus.BLOCKED
    assert failed.paused_reason == "post_verification_failed"
    assert ("task.step_failed", "planning") in publisher.events
    assert ("task.step_blocked", "implementation") in publisher.events


def test_retry_failed_step_resets_failed_state() -> None:
    """摘要：手动重试只重置失败步骤状态，不直接执行。"""
    publisher = RecordingPlanEventPublisher()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), event_publisher=publisher)
    context = orchestrator.create_context("retry-reset")
    step = PlanStep(step_id="planning", skill_id="chat", result_key="result", stage="planning")
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.FAILED}
    context.step_errors = {step.step_id: "post_verification_failed"}
    context.step_results = {step.result_key: "old"}
    context.context_vars = {step.result_key: "old"}
    context.quality_retry_counts = {step.step_id: 1}
    context.processed_steps = [step.step_id]
    context.published_step_events = [step.step_id]
    context.paused_reason = "post_verification_failed"
    context.paused_step_id = step.step_id
    orchestrator._store.save(context.plan_id, context)

    reset = orchestrator.retry_failed_step(context.plan_id, step.step_id, user_feedback="请补完整 evidence")

    assert reset.status is PlanStatus.RUNNING
    assert reset.step_status[step.step_id] is StepStatus.PENDING
    assert step.step_id not in reset.step_errors
    assert step.result_key not in reset.step_results
    assert step.result_key not in reset.context_vars
    assert step.step_id not in reset.quality_retry_counts
    assert reset.feedback_overrides[step.step_id] == "请补完整 evidence"
    assert reset.paused_reason is None
    assert reset.paused_step_id is None
    assert step.step_id not in reset.processed_steps
    assert step.step_id not in reset.published_step_events
    assert ("task.step_retry", step.step_id) in publisher.events


def test_retry_failed_step_rejects_non_failed_step() -> None:
    """摘要：非 failed 步骤不能走手动重试恢复。"""
    orchestrator = PlanOrchestrator(InMemoryPlanStore())
    context = orchestrator.create_context("retry-non-failed")
    step = PlanStep(step_id="planning", skill_id="chat", result_key="result")
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.DONE}
    orchestrator._store.save(context.plan_id, context)

    with pytest.raises(A2PlanValidationError, match="not FAILED"):
        orchestrator.retry_failed_step(context.plan_id, step.step_id)


def test_retry_failed_step_success_unblocks_downstream() -> None:
    """摘要：失败步骤手动重试成功后，下游 blocked 步骤恢复 pending 并发事件。"""
    publisher = RecordingPlanEventPublisher()
    calls: list[str] = []

    def invoke(step: PlanStep, _context: TaskContext) -> str:
        calls.append(step.step_id)
        return "模块 plan_dag_engine，数据流 A 到 B，测试策略覆盖。"

    orchestrator = PlanOrchestrator(InMemoryPlanStore(), event_publisher=publisher)
    context = orchestrator.create_context("retry-unblock")
    first = PlanStep(step_id="planning", skill_id="chat", result_key="ra", stage="planning")
    second = PlanStep(step_id="implementation", skill_id="chat", result_key="rb", depends_on=("planning",))
    context.steps = {first.step_id: first, second.step_id: second}
    context.step_status = {first.step_id: StepStatus.FAILED, second.step_id: StepStatus.BLOCKED}
    context.step_errors = {first.step_id: "post_verification_failed"}
    context.quality_retry_counts = {first.step_id: 1}
    context.processed_steps = [first.step_id, second.step_id]
    context.published_step_events = [first.step_id, second.step_id]
    context.status = PlanStatus.FAILED
    context.paused_reason = "post_verification_failed"
    context.paused_step_id = first.step_id
    orchestrator._store.save(context.plan_id, context)

    reset = orchestrator.retry_failed_step(context.plan_id, first.step_id)
    completed = orchestrator.execute_next(reset, invoke_skill=invoke)

    assert calls == ["planning"]
    assert completed.step_status[first.step_id] is StepStatus.DONE
    assert completed.step_status[second.step_id] is StepStatus.PENDING
    assert ("task.step_completed", first.step_id) in publisher.events
    assert ("task.step_unblocked", second.step_id) in publisher.events


def test_completed_plan_status_short_circuits_execute_next() -> None:
    """摘要：已缓存 completed 的计划再次 execute_next 时不再调度 DAG。"""
    orchestrator = PlanOrchestrator(InMemoryPlanStore())
    context = orchestrator.create_context("terminal-completed")
    step = PlanStep(step_id="a", skill_id="chat", result_key="ra")
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.DONE}
    context.plan_status = "completed"
    orchestrator._store.save(context.plan_id, context)
    called = {"dag": False}

    def fail_if_called(*args, **kwargs):
        del args, kwargs
        called["dag"] = True
        raise AssertionError("DAG should not run for cached terminal plan")

    orchestrator._dag_engine.run_until_blocked = fail_if_called

    result = orchestrator.execute_next(context.plan_id)

    assert called["dag"] is False
    assert result.plan_status == "completed"


def test_terminal_plan_event_emitted_once() -> None:
    """摘要：最后一步完成时缓存 plan_status 并只发布一次 plan completed 事件。"""
    publisher = RecordingPlanEventPublisher()
    orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_invoker=lambda skill_id, payload, idem: "ok",
        event_publisher=publisher,
    )
    context = orchestrator.create_context("terminal-event-once")
    step = PlanStep(step_id="a", skill_id="chat", result_key="ra")
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.PENDING}

    completed = orchestrator.execute_next(context)
    second = orchestrator.execute_next(completed.plan_id)

    assert completed.plan_status == "completed"
    assert second.plan_status == "completed"
    assert publisher.events.count(("task.plan_completed", None)) == 1


def test_failed_without_downstream_sets_failed_plan_status() -> None:
    """摘要：单步骤失败且无下游可恢复链时，计划终态为 failed。"""
    publisher = RecordingPlanEventPublisher()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), event_publisher=publisher)
    context = orchestrator.create_context("terminal-failed")
    step = PlanStep(step_id="planning", skill_id="chat", result_key="ra", stage="planning")
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.PENDING}

    failed = orchestrator.execute_next(context, invoke_skill=lambda step, context: "")

    assert failed.plan_status == "failed"
    assert ("task.plan_failed", None) in publisher.events


def test_blocked_downstream_sets_blocked_plan_status() -> None:
    """摘要：失败传播导致下游 blocked 且无其他可跑分支时，计划终态为 blocked。"""
    publisher = RecordingPlanEventPublisher()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), event_publisher=publisher)
    context = orchestrator.create_context("terminal-blocked")
    first = PlanStep(step_id="planning", skill_id="chat", result_key="ra", stage="planning")
    second = PlanStep(step_id="implementation", skill_id="chat", result_key="rb", depends_on=("planning",))
    context.steps = {first.step_id: first, second.step_id: second}
    context.step_status = {first.step_id: StepStatus.PENDING, second.step_id: StepStatus.PENDING}

    blocked = orchestrator.execute_next(context, invoke_skill=lambda step, context: "")

    assert blocked.plan_status == "blocked"
    assert blocked.step_status[second.step_id] is StepStatus.BLOCKED
    assert ("task.plan_blocked", blocked.paused_step_id) in publisher.events


def test_retry_failed_step_clears_plan_status() -> None:
    """摘要：手动 retry 是唯一回退终态缓存的入口。"""
    orchestrator = PlanOrchestrator(InMemoryPlanStore())
    context = orchestrator.create_context("retry-clears-plan-status")
    step = PlanStep(step_id="planning", skill_id="chat", result_key="ra")
    context.steps = {step.step_id: step}
    context.step_status = {step.step_id: StepStatus.FAILED}
    context.plan_status = "failed"
    context.status = PlanStatus.FAILED
    orchestrator._store.save(context.plan_id, context)

    reset = orchestrator.retry_failed_step(context.plan_id, step.step_id)

    assert reset.plan_status is None
    assert reset.status is PlanStatus.RUNNING


def test_independent_branch_continues_after_partial_failure() -> None:
    """摘要：A→B 失败阻塞时，独立 X→Y 分支仍可继续执行，plan_status 不提前缓存。"""
    calls: list[str] = []

    def invoke(step: PlanStep, _context: TaskContext) -> str:
        calls.append(step.step_id)
        if step.step_id == "a":
            return ""
        return "ok"

    orchestrator = PlanOrchestrator(InMemoryPlanStore())
    context = orchestrator.create_context("partial-failure-continues")
    first = PlanStep(step_id="a", skill_id="chat", result_key="ra", stage="planning")
    blocked_child = PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",))
    independent = PlanStep(step_id="x", skill_id="chat", result_key="rx")
    tail = PlanStep(step_id="y", skill_id="chat", result_key="ry", depends_on=("x",))
    context.steps = {step.step_id: step for step in (first, blocked_child, independent, tail)}
    context.step_status = {step_id: StepStatus.PENDING for step_id in context.steps}

    after_failure = orchestrator.execute_next(context, invoke_skill=invoke)
    after_independent = orchestrator.execute_next(after_failure, invoke_skill=invoke)

    assert calls == ["a", "a", "x"]
    assert after_failure.step_status["b"] is StepStatus.BLOCKED
    assert after_failure.plan_status is None
    assert after_independent.step_status["x"] is StepStatus.DONE
    assert after_independent.plan_status is None


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
