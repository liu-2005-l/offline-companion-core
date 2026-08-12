from __future__ import annotations

import pytest

from offline_companion.core.plan_orchestrator import PlanContext, PlanStep, StepStatus
from offline_companion.core.plan_subagent_dispatch import PlanSubagentDispatch
from offline_companion.core.subagent_scheduler import SubagentScheduler
from offline_companion.core.subagent_types import SubagentContext, SubagentResult
from offline_companion.shared.errors import A2PlanExecutionError


class SpyScheduler(SubagentScheduler):
    """摘要：记录 PlanSubagentDispatch 传入的 spawn 参数。"""

    def __init__(self) -> None:
        super().__init__()
        self.spawn_kwargs: dict[str, object] | None = None
        self.spawned: SubagentContext | None = None

    def spawn(self, **kwargs) -> SubagentContext:
        self.spawn_kwargs = dict(kwargs)
        self.spawned = super().spawn(**kwargs)
        return self.spawned

    def run(self, ctx: SubagentContext) -> SubagentResult:
        return SubagentResult(
            subagent_id=ctx.subagent_id,
            status="completed",
            output="done",
            evidence="子 Agent 完成",
        )


def _context(step: PlanStep) -> PlanContext:
    """摘要：构造测试用计划上下文。"""
    return PlanContext(
        plan_id="plan-subagent",
        steps={step.step_id: step},
        step_status={step.step_id: StepStatus.PENDING},
    )


def test_dispatch_returns_result_payload() -> None:
    """摘要：dispatch() 返回含 subagent_role 和 subagent_id 的字典。"""
    scheduler = SpyScheduler()
    step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", subagent_type="implementer")

    payload = PlanSubagentDispatch(scheduler).dispatch(
        _context(step),
        step,
        parent_session_id="parent",
    )

    assert payload["status"] == "completed"
    assert payload["output"] == "done"
    assert payload["subagent_id"] == scheduler.spawned.subagent_id
    assert payload["subagent_role"] == "implementer"


def test_dispatch_raises_without_scheduler() -> None:
    """摘要：无 scheduler 注入时 dispatch() 抛 A2PlanExecutionError。"""
    step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", subagent_type="implementer")

    with pytest.raises(A2PlanExecutionError, match="subagent_scheduler"):
        PlanSubagentDispatch().dispatch(_context(step), step, parent_session_id="parent")


def test_dispatch_passes_plan_id_and_step_id() -> None:
    """摘要：dispatch() 传 plan_id 和 step_id 到 spawn()。"""
    scheduler = SpyScheduler()
    step = PlanStep(
        step_id="s1",
        skill_id="chat",
        result_key="r1",
        title="实现功能",
        description="实现子 Agent 分支",
        files=("src/app.py",),
        subagent_type="reviewer",
    )

    PlanSubagentDispatch(scheduler).dispatch(
        _context(step),
        step,
        parent_session_id="parent-session",
        privacy_mode="ask_before_cloud",
    )

    assert scheduler.spawn_kwargs is not None
    assert scheduler.spawn_kwargs["parent_session_id"] == "parent-session"
    assert scheduler.spawn_kwargs["role"] == "reviewer"
    assert scheduler.spawn_kwargs["task_description"] == "实现子 Agent 分支"
    assert scheduler.spawn_kwargs["allowed_files"] == ["src/app.py"]
    assert scheduler.spawn_kwargs["privacy_mode"] == "ask_before_cloud"
    assert scheduler.spawn_kwargs["plan_id"] == "plan-subagent"
    assert scheduler.spawn_kwargs["step_id"] == "s1"


def test_build_result_payload_contains_subagent_role() -> None:
    """摘要：result_payload 含 subagent_role 字段。"""
    step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", subagent_type="implementer")
    result = SubagentResult(subagent_id="sub-1", status="completed", output="ok")

    payload = PlanSubagentDispatch.build_result_payload(result, step)

    assert payload["subagent_id"] == "sub-1"
    assert payload["subagent_role"] == "implementer"


def test_is_available_false_without_scheduler() -> None:
    """摘要：无 scheduler 时 is_available 返回 False。"""
    assert PlanSubagentDispatch().is_available is False
    assert PlanSubagentDispatch(SpyScheduler()).is_available is True


def test_handle_subagent_error_records_step_error() -> None:
    """摘要：子 Agent 异常会写入步骤错误表。"""
    step = PlanStep(step_id="s1", skill_id="chat", result_key="r1", subagent_type="implementer")
    context = _context(step)

    PlanSubagentDispatch.handle_subagent_error(context, step, RuntimeError("boom"))

    assert context.step_errors["s1"] == "boom"
    assert context.updated_at is not None
