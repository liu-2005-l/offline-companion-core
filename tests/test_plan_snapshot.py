from __future__ import annotations

from offline_companion.core import plan_snapshot
from offline_companion.core.plan_orchestrator import (
    PlanContext,
    PlanStatus,
    PlanStep,
    StepStatus,
    TaskContext,
)


def test_step_round_trip() -> None:
    """摘要：step_to_dict → step_from_dict 往返保留强类型字段。"""
    step = PlanStep(
        step_id="s1",
        skill_id="chat",
        result_key="r1",
        depends_on=("s0",),
        subagent_type="implementer",
        stage="tdd",
        files=("src/app.py",),
    )

    payload = plan_snapshot.step_to_dict(step)
    restored = plan_snapshot.step_from_dict(dict(payload))

    assert restored.step_id == "s1"
    assert restored.depends_on == ("s0",)
    assert restored.subagent_type == "implementer"
    assert restored.stage == "tdd"
    assert restored.files == ("src/app.py",)


def test_step_from_dict_without_subagent_type() -> None:
    """摘要：旧快照没有 subagent_type 字段时恢复为 None。"""
    payload = {"step_id": "s1", "skill_id": "chat", "result_key": "r1"}

    step = plan_snapshot.step_from_dict(payload)

    assert step.subagent_type is None


def test_serialize_deserialize_plan_context() -> None:
    """摘要：PlanContext 序列化/反序列化往返保留状态、结果和扩展字段。"""
    step = PlanStep(
        step_id="s1",
        skill_id="chat",
        result_key="r1",
        stage="review",
        subagent_type="reviewer",
    )
    context = PlanContext(
        plan_id="p1",
        status=PlanStatus.PAUSED,
        steps={"s1": step},
        step_status={"s1": StepStatus.BLOCKED},
        step_results={"s1": {"result": "done"}},
        step_errors={"s1": "blocked"},
        step_attempts={"s1": 2},
        processed_steps=["s1"],
        published_step_events=["s1"],
        context_vars={"session_id": "sess-1"},
        paused_reason="waiting_consent",
        paused_step_id="s1",
        plan_status="blocked",
        step_started_at={"s1": 1.0},
        step_completed_at={"s1": 2.0},
        step_consent_requests={"s1": {"request_id": "cr-1"}},
        step_route_decisions={"s1": {"mode": "local"}},
        feedback_overrides={"s1": "请补测试证据"},
        quality_retry_counts={"s1": 1},
    )

    restored = plan_snapshot.deserialize(plan_snapshot.serialize(context))

    assert isinstance(restored, TaskContext)
    assert restored.plan_id == "p1"
    assert restored.status is PlanStatus.PAUSED
    assert restored.steps["s1"].subagent_type == "reviewer"
    assert restored.step_status["s1"] is StepStatus.BLOCKED
    assert restored.step_results["s1"] == {"result": "done"}
    assert restored.step_consent_requests["s1"]["request_id"] == "cr-1"
    assert restored.step_route_decisions["s1"]["mode"] == "local"
    assert restored.feedback_overrides["s1"] == "请补测试证据"
    assert restored.quality_retry_counts["s1"] == 1
    assert restored.plan_status == "blocked"


def test_task_context_snapshot_methods_delegate_to_plan_snapshot() -> None:
    """摘要：TaskContext 原有 to_snapshot/from_snapshot 公共 API 保持可用。"""
    context = TaskContext(
        plan_id="p1",
        steps={"s1": PlanStep(step_id="s1", skill_id="chat", result_key="r1")},
        step_status={"s1": StepStatus.PENDING},
    )

    restored = TaskContext.from_snapshot(context.to_snapshot())

    assert restored.plan_id == "p1"
    assert restored.steps["s1"].step_id == "s1"


def test_normalize_subagent_role() -> None:
    """摘要：角色归一化合法值通过，非法值降级为 None。"""
    assert plan_snapshot.normalize_subagent_role("implementer") == "implementer"
    assert plan_snapshot.normalize_subagent_role("reviewer") == "reviewer"
    assert plan_snapshot.normalize_subagent_role(None) is None
    assert plan_snapshot.normalize_subagent_role("invalid") is None
