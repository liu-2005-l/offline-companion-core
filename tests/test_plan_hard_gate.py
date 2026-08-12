from __future__ import annotations

import sqlite3

from offline_companion.core.hard_gate import HardGate
from offline_companion.core.plan_orchestrator import (
    InMemoryPlanStore,
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
    StepStatus,
    TaskContext,
)
from offline_companion.core.skill_execution_tracker import SkillExecutionTracker

STAGES = ["brainstorming", "planning", "tdd", "review", "finalize"]


def _tracker_and_gate(tmp_path) -> tuple[SkillExecutionTracker, HardGate]:
    tracker = SkillExecutionTracker(sqlite3.connect(tmp_path / "plan_gate.db"))
    return tracker, HardGate(tracker)


def _context(step: PlanStep, *, session_id: str = "sess1") -> TaskContext:
    return TaskContext(
        plan_id="plan-gate",
        steps={step.step_id: step},
        step_status={step.step_id: StepStatus.PENDING},
        context_vars={
            "session_id": session_id,
            "skill_name": "coding-agent",
            "skill_stages": list(STAGES),
        },
    )


def test_execute_next_blocks_stage_when_prerequisite_missing(tmp_path) -> None:
    tracker, gate = _tracker_and_gate(tmp_path)
    orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_invoker=lambda skill_id, payload, idem: "ok",
        hard_gate=gate,
        skill_tracker=tracker,
    )
    context = _context(
        PlanStep(
            step_id="planning",
            skill_id="chat",
            result_key="result",
            stage="planning",
        )
    )

    blocked = orchestrator.execute_next(context)

    assert blocked.status is PlanStatus.PAUSED
    assert blocked.paused_reason == "hard_gate_blocked"
    assert blocked.paused_step_id == "planning"
    assert blocked.step_status["planning"] is StepStatus.BLOCKED
    assert blocked.context_vars["hard_gate"]["missing_stages"] == ["brainstorming"]
    assert tracker.get_progress("sess1", "coding-agent") == []


def test_execute_next_allows_first_stage_and_writes_evidence(tmp_path) -> None:
    tracker, gate = _tracker_and_gate(tmp_path)
    orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_invoker=lambda skill_id, payload, idem: {"result": "需求已明确", "evidence": "测试证据"},
        hard_gate=gate,
        skill_tracker=tracker,
    )
    context = _context(
        PlanStep(
            step_id="brainstorming",
            skill_id="chat",
            result_key="result",
            stage="brainstorming",
            verification="需求文档包含输入输出约束。",
        )
    )

    completed = orchestrator.execute_next(context)
    progress = tracker.get_progress("sess1", "coding-agent")

    assert completed.status is PlanStatus.DONE
    assert progress[0]["stage"] == "brainstorming"
    assert progress[0]["status"] == "completed"
    assert progress[0]["evidence"] == "测试证据"


def test_execute_next_allows_stage_after_prerequisite_completed(tmp_path) -> None:
    tracker, gate = _tracker_and_gate(tmp_path)
    tracker.start_stage("sess1", "coding-agent", "brainstorming")
    tracker.complete_stage("sess1", "coding-agent", "brainstorming", "需求已明确")
    orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_invoker=lambda skill_id, payload, idem: "ok",
        hard_gate=gate,
        skill_tracker=tracker,
    )
    context = _context(
        PlanStep(
            step_id="planning",
            skill_id="chat",
            result_key="result",
            stage="planning",
            verification="计划包含可验证步骤。",
        )
    )

    completed = orchestrator.execute_next(context)
    progress = tracker.get_progress("sess1", "coding-agent")

    assert completed.status is PlanStatus.DONE
    assert progress[-1]["stage"] == "planning"
    assert progress[-1]["status"] == "completed"
    assert progress[-1]["evidence"] == "计划包含可验证步骤。"


def test_execute_next_without_skill_or_gate_keeps_existing_behavior(tmp_path) -> None:
    tracker, gate = _tracker_and_gate(tmp_path)
    no_skill = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_invoker=lambda skill_id, payload, idem: "ok",
        hard_gate=gate,
        skill_tracker=tracker,
    )
    no_gate = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_invoker=lambda skill_id, payload, idem: "ok",
        hard_gate=None,
        skill_tracker=None,
    )
    plain_context = TaskContext(
        plan_id="plain",
        steps={"s1": PlanStep(step_id="s1", skill_id="chat", result_key="result", stage="planning")},
        step_status={"s1": StepStatus.PENDING},
    )
    gated_context = _context(PlanStep(step_id="s2", skill_id="chat", result_key="result", stage="planning"))

    assert no_skill.execute_next(plain_context).status is PlanStatus.DONE
    assert no_gate.execute_next(gated_context).status is PlanStatus.DONE


def test_execute_next_marks_stage_failed_on_execution_error(tmp_path) -> None:
    tracker, gate = _tracker_and_gate(tmp_path)

    def fail(_skill_id: str, _payload: dict[str, object], _idempotency_key: str | None) -> object:
        raise RuntimeError("boom")

    orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_invoker=fail,
        hard_gate=gate,
        skill_tracker=tracker,
    )
    context = _context(PlanStep(step_id="brainstorming", skill_id="chat", result_key="result", stage="brainstorming"))

    failed = orchestrator.execute_next(context)
    progress = tracker.get_progress("sess1", "coding-agent")

    assert failed.status is PlanStatus.FAILED
    assert progress[0]["stage"] == "brainstorming"
    assert progress[0]["status"] == "failed"
    assert "boom" in str(progress[0]["evidence"])


def test_resolve_skill_records_coding_agent_stages() -> None:
    orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_resolver=lambda user_input: ("coding-agent", list(STAGES)) if "代码" in user_input else (None, []),
    )

    orchestrator.decide("请帮我写代码修复 Python 脚本缺陷")

    assert orchestrator._skill_name == "coding-agent"
    assert orchestrator._skill_stages == STAGES
