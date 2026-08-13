"""plan_dag_engine：计划 DAG 校验与逐步执行循环。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from offline_companion.core.plan_enums import PlanErrorCode

if TYPE_CHECKING:
    from offline_companion.core.plan_orchestrator import PlanStep, TaskContext

_FINAL_STEP_STATUS_VALUES = {"done", "failed", "skipped", "degraded", "cancelled"}
_DEPENDENCY_SATISFIED_STATUS_VALUES = {"done", "skipped", "degraded"}
_DEPENDENCY_FAILED_STATUS_VALUES = {"failed", "blocked", "cancelled"}
_PENDING_STATUS_VALUE = "pending"
_READY_STATUS_VALUE = "ready"
_RUNNING_STATUS_VALUE = "running"
_BLOCKED_STATUS_VALUE = "blocked"
_SKIPPED_STATUS_VALUE = "skipped"
_DEGRADED_STATUS_VALUE = "degraded"
_FAILED_STATUS_VALUE = "failed"
_DONE_STATUS_VALUE = "done"
_CANCELLED_STATUS_VALUE = "cancelled"
_PLAN_RUNNING_VALUE = "running"
_PLAN_PAUSED_VALUE = "paused"
_PLAN_FAILED_VALUE = "failed"
_PLAN_DONE_VALUE = "done"


class PlanDAGEngine:
    """摘要：校验计划 DAG，并按依赖关系执行至阻塞或终态。"""

    @staticmethod
    def validate_dag(steps: Mapping[str, PlanStep]) -> None:
        """摘要：校验步骤依赖存在且无环。"""
        from offline_companion.shared.errors import A2PlanValidationError

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visited:
                return
            if step_id in visiting:
                raise A2PlanValidationError(f"plan contains dependency cycle at step {step_id!r}")
            if step_id not in steps:
                raise A2PlanValidationError(f"missing step {step_id!r}")
            visiting.add(step_id)
            for dep in steps[step_id].depends_on:
                if dep not in steps:
                    raise A2PlanValidationError(f"step {step_id!r} depends on missing step {dep!r}")
                visit(dep)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in steps:
            visit(step_id)

    @staticmethod
    def is_retryable(error: Exception) -> bool:
        """摘要：判断异常是否允许按步骤 retry 策略重试。"""
        return isinstance(error, (RuntimeError, TimeoutError, ConnectionError))

    def run_until_blocked(
        self,
        context: TaskContext,
        step_executor: Callable[[PlanStep, dict[str, Any]], Any],
        *,
        sleep_fn: Callable[[float], None] | None = None,
        max_steps: int | None = None,
    ) -> TaskContext:
        """摘要：按 DAG 依赖执行计划，直到终态、暂停、失败或达到 max_steps。"""
        if context.is_terminal():
            return context

        context._rebuild_dependency_satisfied_set()
        context.status = _enum_for_value(context.status, _PLAN_RUNNING_VALUE)
        context.mark_started()
        context.paused_reason = None
        context.paused_step_id = None
        sleeper = sleep_fn or (lambda seconds: None)
        steps_executed = 0

        while True:
            ready_steps = self.resolve_ready_steps(context)
            if not ready_steps:
                if self.all_steps_final(context):
                    context.status = _enum_for_value(context.status, _PLAN_DONE_VALUE)
                    context.mark_terminal()
                elif self.all_dependencies_failed(context):
                    failed_deps = self.collect_first_failed_deps(context)
                    context.status = _enum_for_value(context.status, _PLAN_FAILED_VALUE)
                    context.error = f"upstream dependencies failed: {', '.join(failed_deps)}"
                    for step_id, status in list(context.step_status.items()):
                        if _status_value(status) in _DEPENDENCY_FAILED_STATUS_VALUES:
                            self.propagate_failure(context, step_id)
                    context.mark_terminal()
                else:
                    context.status = _enum_for_value(context.status, _PLAN_PAUSED_VALUE)
                    context.paused_reason = "waiting_dependencies"
                    context.touch()
                break

            step = ready_steps[0]
            if step.require_consent and _status_value(context.step_status.get(step.step_id)) != _READY_STATUS_VALUE:
                context.status = _enum_for_value(context.status, _PLAN_PAUSED_VALUE)
                context.paused_reason = PlanErrorCode.WAITING_CONSENT.value
                context.paused_step_id = step.step_id
                context.step_status[step.step_id] = _step_enum(context, _BLOCKED_STATUS_VALUE)
                context.touch()
                break

            if not self.check_condition(step, context.context_vars):
                context.step_status[step.step_id] = _step_enum(context, _SKIPPED_STATUS_VALUE)
                context.mark_step_completed(step.step_id)
                self.mark_completed(context, step.step_id)
                continue

            result, error = self.execute_with_retry(step, context, step_executor, sleep_fn=sleeper)
            steps_executed += 1
            if error is not None:
                if step.degrade_value is not None:
                    context.step_status[step.step_id] = _step_enum(context, _DEGRADED_STATUS_VALUE)
                    context.set_step_result(step.step_id, step.degrade_value)
                    context.step_errors[step.step_id] = str(error)
                    context.mark_step_completed(step.step_id)
                    self.mark_completed(context, step.step_id)
                    if max_steps is not None and steps_executed >= max_steps:
                        if self.all_steps_final(context):
                            context.status = _enum_for_value(context.status, _PLAN_DONE_VALUE)
                            context.mark_terminal()
                        break
                    continue
                context.step_status[step.step_id] = _step_enum(context, _FAILED_STATUS_VALUE)
                context.step_errors[step.step_id] = str(error)
                context.mark_step_completed(step.step_id)
                context.mark_processed(step.step_id)
                if step.fail_fast:
                    context.status = _enum_for_value(context.status, _PLAN_FAILED_VALUE)
                    context.error = str(error)
                    context.paused_step_id = step.step_id
                    context.mark_terminal()
                    break
                if max_steps is not None and steps_executed >= max_steps:
                    break
                continue

            context.step_status[step.step_id] = _step_enum(context, _DONE_STATUS_VALUE)
            context.set_step_result(step.step_id, result)
            context.mark_step_completed(step.step_id)
            self.mark_completed(context, step.step_id)
            if max_steps is not None and steps_executed >= max_steps:
                if self.all_steps_final(context):
                    context.status = _enum_for_value(context.status, _PLAN_DONE_VALUE)
                    context.mark_terminal()
                break

        return context

    def execute_with_retry(
        self,
        step: PlanStep,
        context: TaskContext,
        step_executor: Callable[[PlanStep, dict[str, Any]], Any],
        *,
        sleep_fn: Callable[[float], None],
    ) -> tuple[Any, Exception | None]:
        """摘要：执行单个步骤并按 retry_max/retry_backoff_s 重试。"""
        attempts = 0
        while attempts <= step.retry_max:
            attempts += 1
            context.step_attempts[step.step_id] = attempts
            context.step_status[step.step_id] = _step_enum(context, _RUNNING_STATUS_VALUE)
            context.mark_step_started(step.step_id)
            try:
                return step_executor(step, context.context_vars), None
            except Exception as exc:
                if attempts >= step.retry_max or not self.is_retryable(exc):
                    return None, exc
                if step.retry_backoff_s > 0:
                    sleep_fn(step.retry_backoff_s)
        return None, RuntimeError("unreachable retry state")

    def resolve_ready_steps(self, context: TaskContext) -> list[PlanStep]:
        """摘要：返回当前依赖已满足且仍可执行的步骤。"""
        return context.get_ready_steps()

    def check_condition(self, step: PlanStep, context_vars: Mapping[str, Any]) -> bool:
        """摘要：检查步骤条件键是否满足。"""
        if not step.condition_key:
            return True
        return bool(context_vars.get(step.condition_key))

    def all_steps_final(self, context: TaskContext) -> bool:
        """摘要：判断所有步骤是否均已进入终态。"""
        return all(_status_value(context.step_status.get(step_id)) in _FINAL_STEP_STATUS_VALUES for step_id in context.steps)

    def all_dependencies_failed(self, context: TaskContext) -> bool:
        """摘要：判断所有未终态步骤是否都因上游失败而不可执行。"""
        pending = [
            step
            for step_id, step in context.steps.items()
            if _status_value(context.step_status.get(step_id)) not in _FINAL_STEP_STATUS_VALUES
        ]
        return bool(pending) and all(context.dependency_failed(step) for step in pending)

    def collect_first_failed_deps(self, context: TaskContext) -> list[str]:
        """摘要：收集最多三个失败依赖 ID 供错误信息展示。"""
        failed_set: set[str] = set()
        for step_id, status in context.step_status.items():
            if _status_value(status) in _DEPENDENCY_FAILED_STATUS_VALUES:
                failed_set.add(step_id)
        return sorted(failed_set)[:3]

    def mark_completed(self, context: TaskContext, step_id: str) -> None:
        """摘要：按步骤终态决定是否满足下游依赖。"""
        status = context.step_status.get(step_id)
        if _status_value(status) in _DEPENDENCY_SATISFIED_STATUS_VALUES:
            context.mark_dependency_satisfied(step_id)
        else:
            context.mark_processed(step_id)

    def propagate_failure(self, context: TaskContext, failed_step_id: str) -> list[str]:
        """摘要：从失败步骤出发，将所有仍可等待的下游步骤标记为阻塞。

        参数：
            context: 当前计划上下文。
            failed_step_id: 已失败的上游步骤 ID。

        返回值：
            本次新增标记为 blocked 的下游 step_id 列表。
        """
        successors = _build_successors(context)
        queue = list(successors.get(failed_step_id, ()))
        visited: set[str] = set()
        blocked: list[str] = []

        while queue:
            step_id = queue.pop(0)
            if step_id in visited:
                continue
            visited.add(step_id)
            queue.extend(successors.get(step_id, ()))

            status = _status_value(context.step_status.get(step_id, _PENDING_STATUS_VALUE))
            if status in {_PENDING_STATUS_VALUE, _READY_STATUS_VALUE}:
                context.step_status[step_id] = _step_enum(context, _BLOCKED_STATUS_VALUE)
                context.mark_step_completed(step_id)
                context.mark_processed(step_id)
                blocked.append(step_id)

        if blocked:
            context.touch()
        return blocked

    def propagate_unblock(self, context: TaskContext, completed_step_id: str) -> list[str]:
        """摘要：从成功恢复的步骤出发，将不再受失败依赖影响的下游阻塞步骤恢复为 pending。

        参数：
            context: 当前计划上下文。
            completed_step_id: 已成功完成的上游步骤 ID。

        返回值：
            本次从 blocked 恢复为 pending 的下游 step_id 列表。
        """
        successors = _build_successors(context)
        queue = list(successors.get(completed_step_id, ()))
        visited: set[str] = set()
        unblocked: list[str] = []

        while queue:
            step_id = queue.pop(0)
            if step_id in visited:
                continue
            visited.add(step_id)

            if _status_value(context.step_status.get(step_id)) == _BLOCKED_STATUS_VALUE:
                dependencies = getattr(context.steps.get(step_id), "depends_on", ())
                has_failed_dependency = any(
                    _status_value(context.step_status.get(str(dep), _PENDING_STATUS_VALUE))
                    in _DEPENDENCY_FAILED_STATUS_VALUES
                    for dep in dependencies
                )
                if not has_failed_dependency:
                    context.step_status[step_id] = _step_enum(context, _PENDING_STATUS_VALUE)
                    context.step_completed_at.pop(step_id, None)
                    context.processed_steps = [item for item in context.processed_steps if item != step_id]
                    context.published_step_events = [item for item in context.published_step_events if item != step_id]
                    unblocked.append(step_id)

            queue.extend(successors.get(step_id, ()))

        if unblocked:
            context.touch()
        return unblocked


def _status_value(status: Any) -> str:
    """摘要：兼容 Enum 或字符串状态，取出状态值。"""
    return str(getattr(status, "value", status))


def _enum_for_value(template: Any, value: str) -> Any:
    """摘要：用已有 Enum 类型构造同类状态；字符串状态则直接返回 value。"""
    enum_type = type(template)
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return value


def _step_enum(context: Any, value: str) -> Any:
    """摘要：根据当前 context 中已有 step_status 推断 StepStatus Enum 类型。"""
    sample = next(iter(context.step_status.values()), None)
    if sample is None:
        return value
    return _enum_for_value(sample, value)


def _build_successors(context: Any) -> dict[str, list[str]]:
    """摘要：按 depends_on 反向构建下游邻接表。"""
    successors: dict[str, list[str]] = {step_id: [] for step_id in context.steps}
    for step_id, step in context.steps.items():
        for dependency in getattr(step, "depends_on", ()):
            successors.setdefault(str(dependency), []).append(step_id)
    return successors
