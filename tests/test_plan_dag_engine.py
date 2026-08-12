from __future__ import annotations

import pytest

from offline_companion.core.plan_dag_engine import PlanDAGEngine
from offline_companion.core.plan_orchestrator import PlanStatus, PlanStep, StepStatus, TaskContext
from offline_companion.shared.errors import A2PlanValidationError


def _context(*steps: PlanStep) -> TaskContext:
    """摘要：构造默认 pending 状态的测试计划上下文。"""
    return TaskContext(
        plan_id="plan-dag",
        steps={step.step_id: step for step in steps},
        step_status={step.step_id: StepStatus.PENDING for step in steps},
    )


def test_validate_dag_rejects_cycle() -> None:
    """摘要：DAG 有循环依赖时校验失败。"""
    steps = {
        "a": PlanStep(step_id="a", skill_id="chat", result_key="ra", depends_on=("b",)),
        "b": PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
    }

    with pytest.raises(A2PlanValidationError, match="dependency cycle"):
        PlanDAGEngine.validate_dag(steps)


def test_validate_dag_passes_valid() -> None:
    """摘要：正常 DAG 校验通过。"""
    steps = {
        "a": PlanStep(step_id="a", skill_id="chat", result_key="ra"),
        "b": PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
    }

    PlanDAGEngine.validate_dag(steps)


def test_run_until_blocked_executes_one_step() -> None:
    """摘要：max_steps=1 时只执行一步就停。"""
    engine = PlanDAGEngine()
    context = _context(
        PlanStep(step_id="a", skill_id="chat", result_key="ra"),
        PlanStep(step_id="b", skill_id="chat", result_key="rb"),
    )
    executed: list[str] = []

    result = engine.run_until_blocked(
        context,
        lambda step, context_vars: executed.append(step.step_id) or f"{step.step_id}-done",
        max_steps=1,
    )

    assert executed == ["a"]
    assert result.status is PlanStatus.RUNNING
    assert result.step_status["a"] is StepStatus.DONE
    assert result.step_status["b"] is StepStatus.PENDING


def test_run_until_blocked_skips_completed_steps() -> None:
    """摘要：已完成的步骤不再执行。"""
    engine = PlanDAGEngine()
    first = PlanStep(step_id="a", skill_id="chat", result_key="ra")
    second = PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",))
    context = _context(first, second)
    context.step_status["a"] = StepStatus.DONE
    context.mark_dependency_satisfied("a")
    executed: list[str] = []

    result = engine.run_until_blocked(
        context,
        lambda step, context_vars: executed.append(step.step_id) or "ok",
        max_steps=1,
    )

    assert executed == ["b"]
    assert result.step_status["a"] is StepStatus.DONE
    assert result.step_status["b"] is StepStatus.DONE
    assert result.status is PlanStatus.DONE


def test_run_until_blocked_respects_dependencies() -> None:
    """摘要：步骤依赖未完成时不执行。"""
    engine = PlanDAGEngine()
    context = _context(
        PlanStep(step_id="a", skill_id="chat", result_key="ra"),
        PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
    )
    executed: list[str] = []

    first = engine.run_until_blocked(
        context,
        lambda step, context_vars: executed.append(step.step_id) or "ok",
        max_steps=1,
    )
    second = engine.run_until_blocked(
        first,
        lambda step, context_vars: executed.append(step.step_id) or "ok",
        max_steps=1,
    )

    assert executed == ["a", "b"]
    assert second.step_status["a"] is StepStatus.DONE
    assert second.step_status["b"] is StepStatus.DONE
    assert second.status is PlanStatus.DONE
