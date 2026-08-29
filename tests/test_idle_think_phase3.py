from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from offline_companion.core.attention_awareness import AttentionContext
from offline_companion.core.goal_manager.manager import ReminderDecision
from offline_companion.core.plan_orchestrator import PlanContext, PlanStatus, PlanStep, StepStatus
from offline_companion.shared.types import ReminderCandidate
from offline_companion.shell.idle_think_coordinator import IdleThinkCoordinator
from offline_companion.shell.ui_host.desktop.idle_detector import IdleDetector


class FakeClock:
    """摘要：用于空闲检测器测试的可控时钟。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_idle_detector_touch_resets_timer() -> None:
    clock = FakeClock()
    detector = IdleDetector(threshold_seconds=10, check_interval_seconds=1, clock=clock)

    clock.now = 1025.0
    detector.touch()

    assert detector.last_input_at == 1025.0


def test_idle_detector_check_once_triggers_after_threshold() -> None:
    triggered: list[bool] = []
    clock = FakeClock()
    detector = IdleDetector(
        threshold_seconds=10,
        check_interval_seconds=1,
        on_idle=lambda: triggered.append(True),
        clock=clock,
    )

    assert detector.check_once(now=1009.0) is False
    assert triggered == []
    assert detector.check_once(now=1010.0) is True
    assert triggered == [True]
    assert detector.last_input_at == 1010.0
    assert detector.last_idle_at == 1010.0


def test_idle_detector_resets_after_trigger_to_avoid_tight_loop() -> None:
    triggered: list[bool] = []
    detector = IdleDetector(
        threshold_seconds=10,
        check_interval_seconds=1,
        on_idle=lambda: triggered.append(True),
        clock=FakeClock(),
    )

    assert detector.check_once(now=1011.0) is True
    assert detector.check_once(now=1011.1) is False

    assert triggered == [True]


def test_idle_detector_callback_failure_is_swallowed() -> None:
    detector = IdleDetector(
        threshold_seconds=10,
        check_interval_seconds=1,
        on_idle=MagicMock(side_effect=RuntimeError("boom")),
        clock=FakeClock(),
    )

    assert detector.check_once(now=1010.0) is True


def test_idle_detector_touch_calls_user_input_callback() -> None:
    called: list[bool] = []
    detector = IdleDetector(
        threshold_seconds=10,
        check_interval_seconds=1,
        on_user_input=lambda: called.append(True),
        clock=FakeClock(),
    )

    detector.touch()

    assert called == [True]


def test_idle_detector_user_input_callback_failure_is_swallowed() -> None:
    detector = IdleDetector(
        threshold_seconds=10,
        check_interval_seconds=1,
        on_user_input=MagicMock(side_effect=RuntimeError("boom")),
        clock=FakeClock(),
    )

    detector.touch()


def test_idle_think_coordinator_evaluates_and_writes_snapshot() -> None:
    candidate = ReminderCandidate(
        goal_id="goal-1",
        description="推进论文写作",
        urgency=0.8,
        reason="截止时间临近",
        priority="high",
        deadline=None,
        progress=0.4,
        days_since_last_reminder=2.0,
    )
    context = AttentionContext(is_focus_mode=False)
    decision = ReminderDecision(candidates_to_show=[candidate], candidates_silent=[], context=context)
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = decision
    state_manager = MagicMock()

    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        attention_context_provider=lambda: context,
    )
    coordinator.on_idle()

    goal_manager.evaluate_reminders.assert_called_once()
    assert goal_manager.evaluate_reminders.call_args.args[0].is_idle is True
    state_manager.set_system_state.assert_any_call(
        "idle_think_requested",
        False,
        actor="idle_think",
    )
    snapshot_call = state_manager.set_system_state.call_args_list[0]
    assert snapshot_call.args[0] == "idle_think_result"
    snapshot = snapshot_call.args[1]
    assert snapshot["total_candidates"] == 1
    assert snapshot["show_candidates"] == 1
    assert snapshot["silent_candidates"] == 0
    assert snapshot["candidates_to_show"][0]["goal_id"] == "goal-1"
    assert snapshot["executed"] is False
    assert snapshot["context"]["is_idle"] is True
    assert snapshot["context"]["last_idle_at"] is not None


def test_idle_think_coordinator_runs_memory_maintenance_hook() -> None:
    """摘要：IdleThink 空闲入口会调用语义记忆维护 hook。"""
    context = AttentionContext(is_focus_mode=False)
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = ReminderDecision(
        candidates_to_show=[],
        candidates_silent=[],
        context=context,
    )
    state_manager = MagicMock()
    memory_maintenance = MagicMock(return_value=["extracted 1 events from residual turns"])

    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        attention_context_provider=lambda: context,
        memory_maintenance=memory_maintenance,
    )
    coordinator.on_idle()

    memory_maintenance.assert_called_once_with(300.0)
    goal_manager.evaluate_reminders.assert_called_once()


def test_idle_think_context_reads_focus_mode_and_last_reminder() -> None:
    context = AttentionContext()
    decision = ReminderDecision(candidates_to_show=[], candidates_silent=[], context=context)
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = decision
    state_manager = MagicMock()
    state_manager.get_system_state.return_value = {"status": "completed", "timestamp": 1234.5}
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        attention_context_provider=lambda: context,
        settings_provider=lambda: {"focus_mode_enabled": True},
    )

    coordinator.on_idle()

    evaluated_context = goal_manager.evaluate_reminders.call_args.args[0]
    assert evaluated_context.is_idle is True
    assert evaluated_context.is_focus_mode is True
    assert evaluated_context.last_global_reminder_at == 1234.5


def test_idle_think_context_ignores_invalid_last_reminder() -> None:
    context = AttentionContext()
    decision = ReminderDecision(candidates_to_show=[], candidates_silent=[], context=context)
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = decision
    state_manager = MagicMock()
    state_manager.get_system_state.return_value = {"status": "completed", "timestamp": "not-a-number"}
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        attention_context_provider=lambda: context,
    )

    coordinator.on_idle()

    assert goal_manager.evaluate_reminders.call_args.args[0].last_global_reminder_at is None


def test_idle_think_coordinator_failure_still_clears_requested_flag() -> None:
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.side_effect = RuntimeError("boom")
    state_manager = MagicMock()
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
    )

    coordinator.on_idle()

    state_manager.set_system_state.assert_called_once_with(
        "idle_think_requested",
        False,
        actor="idle_think",
    )


def test_idle_think_sample_maintenance_runs_once_after_daily_success(monkeypatch) -> None:
    monkeypatch.setattr("offline_companion.shell.idle_think_coordinator.time.time", lambda: 1_800_000_000.0)
    state: dict[str, object] = {}
    state_manager = MagicMock()
    state_manager.get_system_state.side_effect = lambda key: state.get(key)

    def save_state(key, value, **_kwargs):
        state[key] = value

    state_manager.set_system_state.side_effect = save_state
    maintenance = MagicMock(return_value=["1:cold"])
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = ReminderDecision(
        candidates_to_show=[],
        candidates_silent=[],
        context=AttentionContext(),
    )
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        sample_maintenance=maintenance,
    )

    coordinator.on_idle()
    coordinator.on_idle()

    maintenance.assert_called_once_with(1_800_000_000.0)
    receipt = state["maintenance:decomp_samples:2027-01-15"]
    assert receipt["executed"] is True
    assert receipt["actions"] == ["1:cold"]


def test_idle_think_failed_sample_maintenance_retries_without_receipt(monkeypatch) -> None:
    monkeypatch.setattr("offline_companion.shell.idle_think_coordinator.time.time", lambda: 1_800_000_000.0)
    state: dict[str, object] = {}
    state_manager = MagicMock()
    state_manager.get_system_state.side_effect = lambda key: state.get(key)

    def save_state(key, value, **_kwargs):
        state[key] = value

    state_manager.set_system_state.side_effect = save_state
    maintenance = MagicMock(side_effect=[RuntimeError("temporary"), []])
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = ReminderDecision(
        candidates_to_show=[],
        candidates_silent=[],
        context=AttentionContext(),
    )
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        sample_maintenance=maintenance,
    )

    coordinator.on_idle()
    receipt_key = "maintenance:decomp_samples:2027-01-15"
    assert receipt_key not in state
    coordinator.on_idle()

    assert maintenance.call_count == 2
    assert state[receipt_key]["executed"] is True


def test_idle_think_candidates_trigger_plan_creation() -> None:
    candidate = ReminderCandidate(
        goal_id="goal-1",
        description="整理 Phase 3 IdleThink 方案",
        urgency=0.9,
        reason="高优先级目标",
        priority="high",
        deadline=None,
        progress=0.2,
        days_since_last_reminder=3.0,
    )
    decision = ReminderDecision(candidates_to_show=[candidate], candidates_silent=[], context=AttentionContext())
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = decision
    state_manager = MagicMock()
    step = PlanStep(
        step_id="step_0",
        skill_id="chat",
        result_key="step_0_result",
        title="明确任务",
        description="明确 IdleThink 的下一步任务",
        expected_output="任务清单",
        verification="检查任务清单存在",
        completion_criteria="清单可执行",
        estimated_minutes=5,
    )
    plan_orchestrator = MagicMock()
    plan_orchestrator.decide.return_value = [step]
    plan_orchestrator.create_plan.return_value = SimpleNamespace(
        plan_id="idle_test",
        status=SimpleNamespace(value="pending"),
    )
    plan_orchestrator.execute_next = MagicMock()
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        plan_orchestrator=plan_orchestrator,
    )

    coordinator.on_idle()

    plan_orchestrator.decide.assert_called_once_with("整理 Phase 3 IdleThink 方案")
    plan_orchestrator.create_plan.assert_called_once()
    plan_orchestrator.execute_next.assert_not_called()
    snapshot = state_manager.set_system_state.call_args_list[0].args[1]
    assert snapshot["idle_plan"]["plan_id"] == "idle_test"
    assert snapshot["idle_plan"]["step_count"] == 1
    assert snapshot["idle_plan"]["steps"][0]["expected_output"] == "任务清单"
    assert snapshot["executed"] is False


def test_idle_think_no_show_candidates_does_not_create_plan() -> None:
    candidate = ReminderCandidate(
        goal_id="goal-1",
        description="静默记录目标",
        urgency=0.4,
        reason="全局冷却中",
        priority="normal",
        deadline=None,
        progress=0.5,
        days_since_last_reminder=1.0,
    )
    decision = ReminderDecision(candidates_to_show=[], candidates_silent=[candidate], context=AttentionContext())
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = decision
    state_manager = MagicMock()
    plan_orchestrator = MagicMock()
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        plan_orchestrator=plan_orchestrator,
    )

    coordinator.on_idle()

    plan_orchestrator.decide.assert_not_called()
    snapshot = state_manager.set_system_state.call_args_list[0].args[1]
    assert snapshot["idle_plan"] is None
    assert snapshot["silent_candidates"] == 1


def test_idle_think_plan_generation_failure_keeps_snapshot() -> None:
    candidate = ReminderCandidate(
        goal_id="goal-1",
        description="会触发失败的目标",
        urgency=0.9,
        reason="测试失败降级",
        priority="high",
        deadline=None,
        progress=0.2,
        days_since_last_reminder=3.0,
    )
    decision = ReminderDecision(candidates_to_show=[candidate], candidates_silent=[], context=AttentionContext())
    goal_manager = MagicMock()
    goal_manager.evaluate_reminders.return_value = decision
    state_manager = MagicMock()
    plan_orchestrator = MagicMock()
    plan_orchestrator.decide.side_effect = RuntimeError("boom")
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        plan_orchestrator=plan_orchestrator,
    )

    coordinator.on_idle()

    snapshot = state_manager.set_system_state.call_args_list[0].args[1]
    assert snapshot["idle_plan"] is None
    assert snapshot["show_candidates"] == 1
    state_manager.set_system_state.assert_any_call(
        "idle_think_requested",
        False,
        actor="idle_think",
    )


def _execution_step(step_id: str, *, depends_on: tuple[str, ...] = ()) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        skill_id="chat",
        result_key=f"{step_id}_result",
        depends_on=depends_on,
        title=f"步骤 {step_id}",
        description=f"执行 {step_id}",
        expected_output=f"{step_id} 输出",
        verification=f"验证 {step_id}",
        completion_criteria=f"{step_id} 完成",
    )


def _execution_context(plan_id: str = "idle_exec") -> PlanContext:
    step_1 = _execution_step("s1")
    step_2 = _execution_step("s2", depends_on=("s1",))
    return PlanContext(
        plan_id=plan_id,
        steps={step_1.step_id: step_1, step_2.step_id: step_2},
        step_status={step_1.step_id: StepStatus.PENDING, step_2.step_id: StepStatus.PENDING},
    )


def _mark_step_done(context: PlanContext, step_id: str, result: str) -> PlanContext:
    context.step_status[step_id] = StepStatus.DONE
    context.set_step_result(step_id, result)
    context.mark_step_completed(step_id)
    context.mark_dependency_satisfied(step_id)
    if all(status is StepStatus.DONE for status in context.step_status.values()):
        context.status = PlanStatus.DONE
        context.mark_terminal()
    else:
        context.status = PlanStatus.RUNNING
    return context


def _sequential_executor(context: PlanContext, steps: list[tuple[str, str]]):
    """摘要：创建按调用顺序完成步骤的 fake execute_next。"""
    pending = list(steps)

    def execute(current: PlanContext) -> PlanContext:
        del current
        step_id, result = pending.pop(0)
        return _mark_step_done(context, step_id, result)

    return execute


def test_idle_think_executes_plan_steps_sequentially() -> None:
    context = _execution_context()
    state_manager = MagicMock()
    state_manager.get_system_state.return_value = None
    plan_orchestrator = MagicMock()
    plan_orchestrator.load_context.return_value = context
    plan_orchestrator.execute_next.side_effect = _sequential_executor(context, [("s1", "ev1"), ("s2", "ev2")])
    coordinator = IdleThinkCoordinator(
        goal_manager=MagicMock(),
        state_manager=state_manager,
        plan_orchestrator=plan_orchestrator,
    )

    coordinator._execute_plan_steps("idle_exec")

    assert plan_orchestrator.execute_next.call_count == 2
    status_payloads = [
        call.args[1]
        for call in state_manager.set_system_state.call_args_list
        if call.args and call.args[0] == "idle_think_status"
    ]
    assert status_payloads[-1]["status"] == "completed"


def test_idle_think_user_input_interrupts_after_current_step() -> None:
    context = _execution_context()
    state_manager = MagicMock()
    state_manager.get_system_state.return_value = None
    plan_orchestrator = MagicMock()
    plan_orchestrator.load_context.return_value = context
    coordinator = IdleThinkCoordinator(
        goal_manager=MagicMock(),
        state_manager=state_manager,
        plan_orchestrator=plan_orchestrator,
    )

    def execute_once(current: PlanContext) -> PlanContext:
        del current
        coordinator.on_user_input()
        return _mark_step_done(context, "s1", "ev1")

    plan_orchestrator.execute_next.side_effect = execute_once

    coordinator._execute_plan_steps("idle_exec")

    assert plan_orchestrator.execute_next.call_count == 1
    plan_orchestrator.pause.assert_called_once_with("idle_exec", reason="user_input")
    status_payloads = [
        call.args[1]
        for call in state_manager.set_system_state.call_args_list
        if call.args and call.args[0] == "idle_think_status"
    ]
    assert status_payloads[-1]["status"] == "paused"
    assert status_payloads[-1]["reason"] == "user_input"


def test_idle_think_execute_exception_does_not_crash() -> None:
    context = _execution_context()
    state_manager = MagicMock()
    state_manager.get_system_state.return_value = None
    plan_orchestrator = MagicMock()
    plan_orchestrator.load_context.return_value = context
    plan_orchestrator.execute_next.side_effect = RuntimeError("boom")
    coordinator = IdleThinkCoordinator(
        goal_manager=MagicMock(),
        state_manager=state_manager,
        plan_orchestrator=plan_orchestrator,
    )

    coordinator._execute_plan_steps("idle_exec")

    status_payloads = [
        call.args[1]
        for call in state_manager.set_system_state.call_args_list
        if call.args and call.args[0] == "idle_think_status"
    ]
    assert status_payloads[-1]["status"] == "failed"
    assert status_payloads[-1]["reason"] == "execute_error"


def test_idle_think_resumes_paused_plan_before_new_evaluation() -> None:
    context = _execution_context("idle_paused")
    state_manager = MagicMock()
    state_manager.get_system_state.return_value = {"plan_id": "idle_paused", "status": "paused"}
    goal_manager = MagicMock()
    plan_orchestrator = MagicMock()
    plan_orchestrator.load_context.return_value = context
    plan_orchestrator.execute_next.side_effect = _sequential_executor(context, [("s1", "ev1"), ("s2", "ev2")])
    coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        plan_orchestrator=plan_orchestrator,
    )

    coordinator.on_idle()

    goal_manager.evaluate_reminders.assert_not_called()
    plan_orchestrator.decide.assert_not_called()
    assert plan_orchestrator.execute_next.call_count == 2


def test_idle_think_writes_progress_for_each_completed_step() -> None:
    context = _execution_context()
    state_manager = MagicMock()
    state_manager.get_system_state.return_value = None
    plan_orchestrator = MagicMock()
    plan_orchestrator.load_context.return_value = context
    plan_orchestrator.execute_next.side_effect = _sequential_executor(context, [("s1", "ev1"), ("s2", "ev2")])
    coordinator = IdleThinkCoordinator(
        goal_manager=MagicMock(),
        state_manager=state_manager,
        plan_orchestrator=plan_orchestrator,
    )

    coordinator._execute_plan_steps("idle_exec")

    progress_payloads = [
        call.args[1]
        for call in state_manager.set_system_state.call_args_list
        if call.args and call.args[0] == "idle_think_progress"
    ]
    assert [item["step_id"] for item in progress_payloads] == ["s1", "s2"]
    assert progress_payloads[0]["result"] == "ev1"
