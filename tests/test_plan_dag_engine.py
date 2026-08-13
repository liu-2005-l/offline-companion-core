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


class TestFailurePropagation:
    """摘要：C-4 后置校验失败后的 DAG 下游阻塞传播。"""

    def test_chain_downstream_blocked(self) -> None:
        """摘要：A→B→C 链路中 A 失败会阻塞 B 和 C。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("b",)),
        )
        context.step_status["a"] = StepStatus.FAILED

        blocked = engine.propagate_failure(context, "a")

        assert blocked == ["b", "c"]
        assert context.step_status["b"] is StepStatus.BLOCKED
        assert context.step_status["c"] is StepStatus.BLOCKED
        assert "b" in context.processed_steps
        assert "c" in context.processed_steps

    def test_completed_downstream_not_overwritten(self) -> None:
        """摘要：已经完成的下游步骤不被覆盖为 blocked。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("b",)),
        )
        context.step_status["a"] = StepStatus.FAILED
        context.step_status["c"] = StepStatus.DONE

        blocked = engine.propagate_failure(context, "a")

        assert blocked == ["b"]
        assert context.step_status["b"] is StepStatus.BLOCKED
        assert context.step_status["c"] is StepStatus.DONE

    def test_diamond_downstream_blocked(self) -> None:
        """摘要：菱形 DAG 中失败会传播到整个下游子图。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("a",)),
            PlanStep(step_id="d", skill_id="chat", result_key="rd", depends_on=("b", "c")),
        )
        context.step_status["a"] = StepStatus.FAILED

        blocked = engine.propagate_failure(context, "a")

        assert set(blocked) == {"b", "c", "d"}
        assert context.step_status["d"] is StepStatus.BLOCKED

    def test_parallel_branch_unaffected(self) -> None:
        """摘要：独立并行链路不受失败传播影响。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
            PlanStep(step_id="x", skill_id="chat", result_key="rx"),
            PlanStep(step_id="y", skill_id="chat", result_key="ry", depends_on=("x",)),
        )
        context.step_status["a"] = StepStatus.FAILED

        blocked = engine.propagate_failure(context, "a")

        assert blocked == ["b"]
        assert context.step_status["x"] is StepStatus.PENDING
        assert context.step_status["y"] is StepStatus.PENDING

    def test_already_failed_downstream_not_overwritten_but_descendant_blocked(self) -> None:
        """摘要：已失败的下游不覆盖，但继续向更深层传播阻塞。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("b",)),
        )
        context.step_status["a"] = StepStatus.FAILED
        context.step_status["b"] = StepStatus.FAILED

        blocked = engine.propagate_failure(context, "a")

        assert blocked == ["c"]
        assert context.step_status["b"] is StepStatus.FAILED
        assert context.step_status["c"] is StepStatus.BLOCKED

    def test_no_downstream_returns_empty(self) -> None:
        """摘要：无下游步骤时传播结果为空。"""
        engine = PlanDAGEngine()
        context = _context(PlanStep(step_id="a", skill_id="chat", result_key="ra"))
        context.step_status["a"] = StepStatus.FAILED

        assert engine.propagate_failure(context, "a") == []


class TestUnblockPropagation:
    """摘要：C-5 失败步骤恢复成功后的下游解除阻塞传播。"""

    def test_chain_unblock(self) -> None:
        """摘要：A→B→C 链路中 A 恢复成功会解除 B 和 C 的阻塞。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("b",)),
        )
        context.step_status.update({"a": StepStatus.DONE, "b": StepStatus.BLOCKED, "c": StepStatus.BLOCKED})
        context.processed_steps = ["a", "b", "c"]
        context.published_step_events = ["b", "c"]

        unblocked = engine.propagate_unblock(context, "a")

        assert unblocked == ["b", "c"]
        assert context.step_status["b"] is StepStatus.PENDING
        assert context.step_status["c"] is StepStatus.PENDING
        assert "b" not in context.processed_steps
        assert "c" not in context.published_step_events

    def test_diamond_unblock(self) -> None:
        """摘要：菱形 DAG 中恢复成功会解除整个下游子图。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("a",)),
            PlanStep(step_id="d", skill_id="chat", result_key="rd", depends_on=("b", "c")),
        )
        context.step_status.update(
            {"a": StepStatus.DONE, "b": StepStatus.BLOCKED, "c": StepStatus.BLOCKED, "d": StepStatus.BLOCKED}
        )

        unblocked = engine.propagate_unblock(context, "a")

        assert set(unblocked) == {"b", "c", "d"}
        assert context.step_status["d"] is StepStatus.PENDING

    def test_multi_parent_partial_unblock_keeps_blocked(self) -> None:
        """摘要：多父依赖中仍有失败上游时，下游保持 blocked。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb"),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("a", "b")),
        )
        context.step_status.update({"a": StepStatus.DONE, "b": StepStatus.FAILED, "c": StepStatus.BLOCKED})

        assert engine.propagate_unblock(context, "a") == []
        assert context.step_status["c"] is StepStatus.BLOCKED

    def test_multi_parent_full_unblock(self) -> None:
        """摘要：多父依赖均无失败/阻塞时，下游恢复为 pending。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb"),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("a", "b")),
        )
        context.step_status.update({"a": StepStatus.DONE, "b": StepStatus.DONE, "c": StepStatus.BLOCKED})

        assert engine.propagate_unblock(context, "a") == ["c"]
        assert context.step_status["c"] is StepStatus.PENDING

    def test_no_blocked_downstream_returns_empty(self) -> None:
        """摘要：下游没有 blocked 步骤时返回空。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
        )
        context.step_status.update({"a": StepStatus.DONE, "b": StepStatus.PENDING})

        assert engine.propagate_unblock(context, "a") == []

    def test_failed_downstream_not_unblocked(self) -> None:
        """摘要：下游自身已 failed 时不回退为 pending。"""
        engine = PlanDAGEngine()
        context = _context(
            PlanStep(step_id="a", skill_id="chat", result_key="ra"),
            PlanStep(step_id="b", skill_id="chat", result_key="rb", depends_on=("a",)),
            PlanStep(step_id="c", skill_id="chat", result_key="rc", depends_on=("b",)),
        )
        context.step_status.update({"a": StepStatus.DONE, "b": StepStatus.FAILED, "c": StepStatus.BLOCKED})

        assert engine.propagate_unblock(context, "a") == []
        assert context.step_status["b"] is StepStatus.FAILED
        assert context.step_status["c"] is StepStatus.BLOCKED
