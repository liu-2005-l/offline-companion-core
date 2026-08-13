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


class TestPostVerification:
    """C-1：HardGate 后置校验。"""

    def test_planning_stage_empty_output_rejected(self) -> None:
        """摘要：planning stage 产出为空时返回 issue。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="planning")

        issues = gateway.verify_post_execution(step, "")

        assert "evidence_missing" in issues
        assert any("planning" in issue for issue in issues)

    def test_planning_stage_with_module_description_passes(self) -> None:
        """摘要：planning stage 产出含模块描述时通过。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="planning")

        issues = gateway.verify_post_execution(step, "需要修改 plan_dag_engine 模块，数据流从 A 到 B")

        assert all("planning" not in issue for issue in issues)

    def test_tdd_stage_without_test_evidence_rejected(self) -> None:
        """摘要：tdd stage 产出无测试证据时返回 issue。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="tdd")

        issues = gateway.verify_post_execution(step, "写了一些代码")

        assert any("tdd" in issue for issue in issues)

    def test_tdd_stage_with_test_evidence_passes(self) -> None:
        """摘要：tdd stage 产出含测试证据时通过。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="tdd")

        issues = gateway.verify_post_execution(step, "运行测试 assert result == expected, passed")

        assert all("tdd" not in issue for issue in issues)

    def test_review_stage_not_approved_rejected(self) -> None:
        """摘要：review stage approved=False 时返回 issue。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="review")

        issues = gateway.verify_post_execution(step, {"approved": False, "issues": ["bug"]})

        assert any("review" in issue for issue in issues)

    def test_review_stage_approved_passes(self) -> None:
        """摘要：review stage approved=True 时通过。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="review")

        issues = gateway.verify_post_execution(step, {"approved": True, "issues": []})

        assert all("review" not in issue for issue in issues)

    def test_implementation_stage_no_code_rejected(self) -> None:
        """摘要：implementation stage 产出无代码痕迹时返回 issue。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="implementation")

        issues = gateway.verify_post_execution(step, "建议你修改这个文件")

        assert any("implementation" in issue for issue in issues)

    def test_implementation_stage_with_code_passes(self) -> None:
        """摘要：implementation stage 产出含代码块时通过。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="implementation")

        issues = gateway.verify_post_execution(step, "已修改：\n```python\ndef foo(): pass\n```")

        assert all("implementation" not in issue for issue in issues)

    def test_no_stage_skips_stage_check(self) -> None:
        """摘要：stage 为空时只校验证据，不校验阶段规范。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="")

        issues = gateway.verify_post_execution(step, "some output")

        assert all(
            token not in issue
            for issue in issues
            for token in ("stage", "planning", "tdd", "implementation", "review", "verification")
        )


class TestRetryFeedback:
    """C-2：后置校验失败时构建重试 feedback。"""

    def test_build_retry_feedback_contains_issues(self) -> None:
        """摘要：feedback 包含所有后置校验失败原因。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="tdd")

        feedback = gateway.build_retry_feedback(step, ["tdd_stage_missing_test_evidence", "evidence_missing"])

        assert "tdd_stage_missing_test_evidence" in feedback
        assert "evidence_missing" in feedback
        assert "tdd" in feedback.lower()

    def test_build_retry_feedback_contains_stage_label(self) -> None:
        """摘要：feedback 包含当前阶段标签。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="planning")

        feedback = gateway.build_retry_feedback(step, ["planning_stage_missing_module_description"])

        assert "planning" in feedback.lower()


class TestStructuredEvidence:
    """C-3：结构化 evidence 校验。"""

    def test_structured_evidence_all_fields_present_passes(self) -> None:
        """摘要：planning evidence 含 modules 和 data_flow 时通过。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="planning")
        result = {
            "output": "模块设计。",
            "evidence": {"modules": ["plan_gateway.py"], "data_flow": "A→B→C"},
        }

        issues = gateway.verify_post_execution(step, result)

        assert not any("evidence_missing_field" in issue for issue in issues)
        assert not any("evidence_empty_field" in issue for issue in issues)

    def test_structured_evidence_missing_field_rejected(self) -> None:
        """摘要：planning evidence 缺 data_flow 时返回 issue。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="planning")
        result = {
            "output": "模块设计。",
            "evidence": {"modules": ["plan_gateway.py"]},
        }

        issues = gateway.verify_post_execution(step, result)

        assert any("data_flow" in issue for issue in issues)

    def test_structured_evidence_empty_field_rejected(self) -> None:
        """摘要：tdd evidence 字段存在但为空时返回 issue。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="tdd")
        result = {
            "output": "测试。",
            "evidence": {"test_command": "", "test_result": "pass"},
        }

        issues = gateway.verify_post_execution(step, result)

        assert any("test_command" in issue for issue in issues)

    def test_no_structured_evidence_falls_back_to_heuristic(self) -> None:
        """摘要：无 evidence dict 时回退到 C-1 启发式。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="planning")

        issues = gateway.verify_post_execution(step, "模块 plan_dag_engine，数据流 A→B")

        assert not any("planning" in issue for issue in issues)

    def test_tdd_structured_evidence_complete(self) -> None:
        """摘要：tdd evidence 完整时通过。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="tdd")
        result = {
            "output": "测试通过。",
            "evidence": {"test_command": "pytest tests/test_plan.py", "test_result": "pass"},
        }

        issues = gateway.verify_post_execution(step, result)

        assert not any("tdd" in issue for issue in issues)

    def test_review_structured_evidence_approved(self) -> None:
        """摘要：review evidence approved=True 时通过。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="review")
        result = {
            "output": "审查通过。",
            "evidence": {"approved": True, "issues": []},
        }

        issues = gateway.verify_post_execution(step, result)

        assert not any("review" in issue for issue in issues)

    def test_review_structured_evidence_rejected(self) -> None:
        """摘要：review evidence approved=False 时返回 issue。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="review")
        result = {
            "output": "审查不通过。",
            "evidence": {"approved": False, "issues": ["内存泄漏"]},
        }

        issues = gateway.verify_post_execution(step, result)

        assert any("review" in issue for issue in issues)

    def test_verification_structured_evidence(self) -> None:
        """摘要：verification evidence 完整时通过。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="verification")
        result = {
            "output": "验证通过。",
            "evidence": {
                "command": "pytest --tb=short",
                "exit_code": 0,
                "output_summary": "607 passed, 3 skipped",
            },
        }

        issues = gateway.verify_post_execution(step, result)

        assert not any("verification" in issue for issue in issues)

    def test_feedback_includes_schema_hint(self) -> None:
        """摘要：结构化字段缺失时 feedback 包含 schema 提示。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="tdd")

        feedback = gateway.build_retry_feedback(step, ["evidence_missing_field:tdd:test_command"])

        assert "test_command" in feedback
        assert "test_result" in feedback
        assert "tdd" in feedback.lower()

    def test_no_stage_skips_structured_check(self) -> None:
        """摘要：stage 为空时只校验 evidence，不走结构化 schema。"""
        gateway = PlanGateway()
        step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", stage="")
        result = {"output": "ok", "evidence": {"foo": "bar"}}

        issues = gateway.verify_post_execution(step, result)

        assert all("evidence_missing_field" not in issue for issue in issues)
        assert all("evidence_empty_field" not in issue for issue in issues)


class TestPlanStatusEvaluation:
    """摘要：C-4 计划整体状态汇总。"""

    def test_all_completed(self) -> None:
        """摘要：所有步骤完成时返回 completed。"""
        context = _context(PlanStep(step_id="a", skill_id="chat", result_key="ra"))
        context.step_status["a"] = StepStatus.DONE

        assert PlanGateway().evaluate_plan_status(context) == "completed"

    def test_blocked_has_priority_over_failed(self) -> None:
        """摘要：存在 blocked 时优先返回 blocked。"""
        first = PlanStep(step_id="a", skill_id="chat", result_key="ra")
        second = PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",))
        context = TaskContext(
            plan_id="status-blocked",
            steps={"a": first, "b": second},
            step_status={"a": StepStatus.FAILED, "b": StepStatus.BLOCKED},
        )

        assert PlanGateway().evaluate_plan_status(context) == "blocked"

    def test_failed_without_blocked(self) -> None:
        """摘要：存在 failed 且无 blocked 时返回 failed。"""
        context = _context(PlanStep(step_id="a", skill_id="chat", result_key="ra"))
        context.step_status["a"] = StepStatus.FAILED

        assert PlanGateway().evaluate_plan_status(context) == "failed"

    def test_in_progress(self) -> None:
        """摘要：存在 pending/ready/running 时返回 in_progress。"""
        context = _context(PlanStep(step_id="a", skill_id="chat", result_key="ra"))

        assert PlanGateway().evaluate_plan_status(context) == "in_progress"
