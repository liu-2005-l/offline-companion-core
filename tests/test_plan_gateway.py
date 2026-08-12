from __future__ import annotations

import sqlite3

import pytest

from offline_companion.core.hard_gate import HardGate
from offline_companion.core.plan_gateway import PlanGateway, verify_evidence
from offline_companion.core.plan_orchestrator import (
    A3ConsentAdapter,
    PlanStatus,
    PlanStep,
    StepStatus,
    TaskContext,
)
from offline_companion.core.skill_execution_tracker import SkillExecutionTracker
from offline_companion.shared.errors import A2PlanValidationError

STAGES = ["brainstorming", "planning", "tdd", "review", "finalize"]


def _tracker_and_gate(tmp_path) -> tuple[SkillExecutionTracker, HardGate]:
    """摘要：构造测试用阶段追踪器与硬门禁。"""
    tracker = SkillExecutionTracker(sqlite3.connect(tmp_path / "gateway.db"))
    return tracker, HardGate(tracker)


def _context(step: PlanStep) -> TaskContext:
    """摘要：构造带 Skill 上下文的单步骤计划。"""
    return TaskContext(
        plan_id="plan-gateway",
        steps={step.step_id: step},
        step_status={step.step_id: StepStatus.PENDING},
        context_vars={
            "session_id": "sess1",
            "skill_name": "coding-agent",
            "skill_stages": list(STAGES),
        },
    )


def test_check_hard_gate_blocks_when_prerequisite_incomplete(tmp_path) -> None:
    """摘要：前置阶段未完成时，HardGate 阻塞。"""
    _tracker, gate = _tracker_and_gate(tmp_path)
    context = _context(PlanStep(step_id="planning", skill_id="chat", result_key="result", stage="planning"))

    blocked = PlanGateway(hard_gate=gate).check_hard_gate(context)

    assert blocked is True
    assert context.status is PlanStatus.PAUSED
    assert context.paused_reason == "hard_gate_blocked"
    assert context.step_status["planning"] is StepStatus.BLOCKED
    assert context.context_vars["hard_gate"]["missing_stages"] == ["brainstorming"]


def test_check_hard_gate_allows_when_prerequisite_complete(tmp_path) -> None:
    """摘要：前置阶段已完成时，HardGate 放行。"""
    tracker, gate = _tracker_and_gate(tmp_path)
    tracker.start_stage("sess1", "coding-agent", "brainstorming")
    tracker.complete_stage("sess1", "coding-agent", "brainstorming", "需求已明确")
    context = _context(PlanStep(step_id="planning", skill_id="chat", result_key="result", stage="planning"))

    blocked = PlanGateway(hard_gate=gate).check_hard_gate(context)

    assert blocked is False
    assert context.status is PlanStatus.PENDING
    assert context.step_status["planning"] is StepStatus.PENDING


def test_prepare_consent_pause_sets_paused_reason() -> None:
    """摘要：consent 暂停时设置 paused_reason=waiting_consent。"""
    step = PlanStep(step_id="cloud", skill_id="cloud", result_key="result", require_consent=True)
    context = _context(step)
    context.paused_step_id = "cloud"

    prepared = PlanGateway().prepare_consent_pause(context)

    assert prepared is True
    assert context.status is PlanStatus.PAUSED
    assert context.paused_reason == "waiting_consent"
    assert context.context_vars["requires_consent"] is True
    assert context.get_step_consent_request("cloud")["request_id"]


def test_apply_consent_decision_resumes_on_approved() -> None:
    """摘要：consent 批准后恢复 plan 执行。"""
    class _Pending:
        decided = True
        allowed = True

    class _Gateway:
        def get_pending(self, request_id: str) -> _Pending:
            assert request_id == "req-1"
            return _Pending()

    step = PlanStep(step_id="cloud", skill_id="cloud", result_key="result", require_consent=True)
    context = _context(step)
    context.status = PlanStatus.PAUSED
    context.paused_reason = "waiting_consent"
    context.paused_step_id = "cloud"
    context.set_step_consent_request("cloud", {"request_id": "req-1"})

    resumed = PlanGateway(consent_gateway=_Gateway()).apply_consent_decision(context, "req-1")

    assert resumed.status is PlanStatus.RUNNING
    assert resumed.paused_step_id is None
    assert resumed.step_status["cloud"] is StepStatus.READY
    assert resumed.context_vars["requires_consent"] is False


def test_apply_consent_decision_blocks_on_denied() -> None:
    """摘要：consent 拒绝后 plan 不恢复。"""
    class _Pending:
        decided = True
        allowed = False

    class _Gateway:
        def get_pending(self, request_id: str) -> _Pending:
            assert request_id == "req-2"
            return _Pending()

    step = PlanStep(step_id="cloud", skill_id="cloud", result_key="result", require_consent=True)
    context = _context(step)
    context.status = PlanStatus.PAUSED
    context.paused_reason = "waiting_consent"
    context.paused_step_id = "cloud"
    context.set_step_consent_request("cloud", {"request_id": "req-2"})

    denied = PlanGateway(consent_gateway=_Gateway()).apply_consent_decision(context, "req-2")

    assert denied.status is PlanStatus.CANCELLED
    assert denied.step_status["cloud"] is StepStatus.CANCELLED
    assert denied.completed_at is not None


def test_verify_evidence_rejects_empty() -> None:
    """摘要：evidence 为空时校验失败。"""
    step = PlanStep(step_id="s1", skill_id="chat", result_key="result")

    with pytest.raises(A2PlanValidationError, match="evidence_missing"):
        verify_evidence(step, {})


def test_prepare_consent_pause_uses_adapter_request_id() -> None:
    """摘要：Consent 适配器返回的 A3 request_id 会写入步骤上下文。"""
    class _Gateway:
        def __init__(self) -> None:
            self.last_artifact = {"request_id": "a3-req"}

        def submit(self, consent_request) -> bool:
            assert consent_request.step_id == "cloud"
            return False

    step = PlanStep(step_id="cloud", skill_id="cloud", result_key="result", require_consent=True)
    context = _context(step)
    context.paused_step_id = "cloud"
    gateway = _Gateway()

    PlanGateway(consent_adapter=A3ConsentAdapter(gateway), consent_gateway=gateway).prepare_consent_pause(context)

    assert context.get_step_consent_request("cloud")["request_id"] == "a3-req"
