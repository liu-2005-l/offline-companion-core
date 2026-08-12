"""plan_orchestrator：A2 任务规划与执行编排。"""

from __future__ import annotations

import dataclasses
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import sleep, time
from typing import Any, Protocol
from uuid import uuid4

from offline_companion.core.state_manager import StateManager
from offline_companion.core.subagent_scheduler import SubagentScheduler
from offline_companion.core.subagent_types import SubagentRole
from offline_companion.shared.errors import (
    A2PlanExecutionError,
    A2PlanTemplateNotFoundError,
    A2PlanValidationError,
)
from offline_companion.shared.types import PurposeType


class StepStatus(Enum):
    """单个步骤运行状态。"""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class PlanStatus(Enum):
    """任务整体运行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINAL_STEP_STATUSES = frozenset(
    {
        StepStatus.DONE,
        StepStatus.FAILED,
        StepStatus.SKIPPED,
        StepStatus.DEGRADED,
        StepStatus.CANCELLED,
    }
)
DEPENDENCY_SATISFIED_STATUSES = frozenset({StepStatus.DONE, StepStatus.SKIPPED, StepStatus.DEGRADED})
DEPENDENCY_FAILED_STATUSES = frozenset({StepStatus.FAILED, StepStatus.CANCELLED})
FINAL_PLAN_STATUSES = frozenset({PlanStatus.DONE, PlanStatus.FAILED, PlanStatus.CANCELLED})
DEFAULT_RETRYABLE_ERRORS = (RuntimeError, TimeoutError, ConnectionError)


@dataclass(frozen=True)
class PlanStep:
    """单个规划步骤的静态定义。

    摘要：
        承载执行字段与计划展示字段。新增的强类型计划字段用于避免
        只靠 ``payload`` 存放自由文本，旧 payload 路径仍保留用于兼容。
    """

    step_id: str
    skill_id: str
    result_key: str
    depends_on: tuple[str, ...] = ()
    condition_key: str | None = None
    retry_max: int = 0
    retry_backoff_s: float = 0.0
    degrade_value: Any = None
    require_consent: bool = False
    idempotency_key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    fail_fast: bool = True
    title: str = ""
    description: str = ""
    expected_output: str = ""
    verification: str = ""
    completion_criteria: str = ""
    stage: str | None = None
    estimated_minutes: int = 0
    files: tuple[str, ...] = ()
    subagent_type: SubagentRole | None = None


@dataclass
class TaskContext:
    """任务唯一真值源，可全量快照持久化。"""

    plan_id: str
    snapshot_version: int = 2
    status: PlanStatus = PlanStatus.PENDING
    steps: dict[str, PlanStep] = field(default_factory=dict)
    step_status: dict[str, StepStatus] = field(default_factory=dict)
    step_results: dict[str, Any] = field(default_factory=dict)
    step_errors: dict[str, str] = field(default_factory=dict)
    step_attempts: dict[str, int] = field(default_factory=dict)
    processed_steps: list[str] = field(default_factory=list)
    published_step_events: list[str] = field(default_factory=list)
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    context_vars: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    paused_reason: str | None = None
    paused_step_id: str | None = None
    started_at: float | None = None
    updated_at: float | None = None
    completed_at: float | None = None
    step_started_at: dict[str, float] = field(default_factory=dict)
    step_completed_at: dict[str, float] = field(default_factory=dict)
    step_consent_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    step_route_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    _dependency_satisfied_set: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        self._rebuild_dependency_satisfied_set()

    @property
    def progress(self) -> float:
        if not self.steps:
            return 1.0
        final_count = sum(1 for step_id in self.steps if self.step_status.get(step_id) in FINAL_STEP_STATUSES)
        return final_count / len(self.steps)

    @property
    def completed_set(self) -> set[str]:
        return set(self._dependency_satisfied_set)

    def mark_dependency_satisfied(self, step_id: str) -> None:
        if step_id not in self.processed_steps:
            self.processed_steps.append(step_id)
        self._dependency_satisfied_set.add(step_id)

    def mark_processed(self, step_id: str) -> None:
        if step_id not in self.processed_steps:
            self.processed_steps.append(step_id)

    def _rebuild_dependency_satisfied_set(self) -> None:
        self._dependency_satisfied_set = {
            step_id for step_id in self.processed_steps
            if self.step_status.get(step_id) in DEPENDENCY_SATISFIED_STATUSES
        }

    def get_ready_steps(self) -> list[PlanStep]:
        completed = self._dependency_satisfied_set
        ready: list[PlanStep] = []
        for step in self.steps.values():
            status = self.step_status.get(step.step_id, StepStatus.PENDING)
            if status not in {StepStatus.PENDING, StepStatus.READY}:
                continue
            if all(dep in completed for dep in step.depends_on):
                ready.append(step)
        return ready

    def is_terminal(self) -> bool:
        return self.status in FINAL_PLAN_STATUSES

    def dependency_failed(self, step: PlanStep) -> list[str]:
        return [dep for dep in step.depends_on if self.step_status.get(dep) in DEPENDENCY_FAILED_STATUSES]

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "snapshot_version": self.snapshot_version,
            "plan_id": self.plan_id,
            "status": self.status.value,
            "steps": {sid: _step_to_dict(step) for sid, step in self.steps.items()},
            "step_status": {sid: status.value for sid, status in self.step_status.items()},
            "step_results": dict(self.step_results),
            "step_errors": dict(self.step_errors),
            "step_attempts": dict(self.step_attempts),
            "processed_steps": list(self.processed_steps),
            "published_step_events": list(self.published_step_events),
            "trace_id": self.trace_id,
            "context_vars": dict(self.context_vars),
            "error": self.error,
            "paused_reason": self.paused_reason,
            "paused_step_id": self.paused_step_id,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "step_started_at": dict(self.step_started_at),
            "step_completed_at": dict(self.step_completed_at),
            "step_consent_requests": dict(self.step_consent_requests),
            "step_route_decisions": dict(self.step_route_decisions),
            "progress": self.progress,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> TaskContext:
        snapshot_version = int(payload.get("snapshot_version", 1))
        steps = {
            str(sid): _step_from_dict(dict(raw_step))
            for sid, raw_step in dict(payload.get("steps", {})).items()
        }
        step_status = {
            str(sid): StepStatus(str(raw_status))
            for sid, raw_status in dict(payload.get("step_status", {})).items()
        }
        processed_steps = list(payload.get("processed_steps", payload.get("completed_steps", [])))
        return cls(
            plan_id=str(payload["plan_id"]),
            snapshot_version=max(2, snapshot_version),
            status=PlanStatus(str(payload.get("status", PlanStatus.PENDING.value))),
            steps=steps,
            step_status=step_status,
            step_results=dict(payload.get("step_results", {})),
            step_errors=dict(payload.get("step_errors", {})),
            step_attempts={str(k): int(v) for k, v in dict(payload.get("step_attempts", {})).items()},
            processed_steps=[str(item) for item in processed_steps],
            published_step_events=[str(item) for item in payload.get("published_step_events", [])],
            trace_id=str(payload.get("trace_id") or uuid4()),
            context_vars=dict(payload.get("context_vars", {})),
            error=payload.get("error"),
            paused_reason=payload.get("paused_reason"),
            paused_step_id=payload.get("paused_step_id"),
            started_at=_optional_float(payload.get("started_at")),
            updated_at=_optional_float(payload.get("updated_at")),
            completed_at=_optional_float(payload.get("completed_at")),
            step_started_at=_float_dict(payload.get("step_started_at")),
            step_completed_at=_float_dict(payload.get("step_completed_at")),
            step_consent_requests=_dict_of_dict(payload.get("step_consent_requests")),
            step_route_decisions=_dict_of_dict(payload.get("step_route_decisions")),
        )

    def touch(self) -> None:
        """摘要：刷新上下文更新时间。"""
        self.updated_at = time()

    def mark_started(self) -> None:
        """摘要：在计划首次进入运行态时写入开始时间。"""
        now = time()
        if self.started_at is None:
            self.started_at = now
        self.updated_at = now

    def mark_terminal(self) -> None:
        """摘要：在计划进入终态时写入完成时间并刷新更新时间。"""
        now = time()
        if self.completed_at is None:
            self.completed_at = now
        self.updated_at = now

    def mark_step_started(self, step_id: str) -> None:
        """摘要：记录单个步骤首次进入运行态的时间。"""
        self.step_started_at.setdefault(step_id, time())
        self.updated_at = time()

    def mark_step_completed(self, step_id: str) -> None:
        """摘要：记录单个步骤进入终态的时间。"""
        self.step_completed_at.setdefault(step_id, time())
        self.updated_at = time()

    def get_step_result(self, step_id: str) -> Any | None:
        """摘要：按 step_id 读取步骤结果。"""
        step = self.steps.get(step_id)
        if step is None:
            return None
        return self.step_results.get(step.result_key)

    def set_step_result(self, step_id: str, result: Any) -> None:
        """摘要：按 step_id 写入步骤结果。"""
        step = self.steps.get(step_id)
        if step is None:
            raise KeyError(f"unknown step_id: {step_id}")
        self.step_results[step.result_key] = result
        self.context_vars[step.result_key] = result
        self.touch()

    def get_context_var(self, key: str, default: Any = None) -> Any:
        """摘要：读取上下文字典中的一个键。"""
        return self.context_vars.get(key, default)

    def set_context_var(self, key: str, value: Any) -> None:
        """摘要：写入上下文字典中的一个键。"""
        self.context_vars[key] = value
        self.touch()

    def get_step_consent_request(self, step_id: str) -> dict[str, Any] | None:
        """摘要：按步骤读取结构化 consent 请求。"""
        payload = self.step_consent_requests.get(step_id)
        if payload is not None:
            return dict(payload)
        legacy = self.context_vars.get("consent_request")
        if isinstance(legacy, Mapping):
            return dict(legacy)
        return None

    def set_step_consent_request(self, step_id: str, payload: dict[str, Any]) -> None:
        """摘要：按步骤写入结构化 consent 请求，并同步兼容层。"""
        data = dict(payload)
        self.step_consent_requests[step_id] = data
        self.context_vars["consent_request"] = data
        self.touch()

    def get_step_route_decision(self, step_id: str) -> dict[str, Any] | None:
        """摘要：按步骤读取结构化 route decision。"""
        payload = self.step_route_decisions.get(step_id)
        if payload is not None:
            return dict(payload)
        legacy = self.context_vars.get("route_decision")
        if isinstance(legacy, Mapping):
            return dict(legacy)
        return None

    def set_step_route_decision(self, step_id: str, payload: dict[str, Any]) -> None:
        """摘要：按步骤写入结构化 route decision，并同步兼容层。"""
        data = dict(payload)
        self.step_route_decisions[step_id] = data
        self.context_vars["route_decision"] = data
        self.touch()


class PlanTemplateNotFoundError(A2PlanTemplateNotFoundError):
    """指定计划模板不存在。"""


@dataclass(frozen=True)
class ConsentRequest:
    """结构化 Consent 请求。"""

    plan_id: str
    step_id: str
    skill_id: str
    operation: str
    purpose_type: PurposeType | str | None = None
    risk_level: str = "medium"
    impact_scope: str = "plan_step"
    source: str = "plan_orchestrator"
    metadata: dict[str, Any] = field(default_factory=dict)


class ConsentAdapter(Protocol):
    """Consent 结构化适配协议。"""

    def request(self, consent_request: ConsentRequest) -> bool:
        """发起 Consent 请求并返回是否批准。"""


class A3ConsentGateway(Protocol):
    """A3 审批入口协议。"""

    def submit(self, consent_request: ConsentRequest) -> bool:
        """提交审批请求并返回是否批准。"""


@dataclass
class A3ConsentAdapter:
    """将 A3 审批入口适配为 PlanOrchestrator 所需的 ConsentAdapter。"""

    gateway: A3ConsentGateway

    def request(self, consent_request: ConsentRequest) -> bool:
        return self.gateway.submit(consent_request)


@dataclass
class PlanContext(TaskContext):
    """PlanAutoBridge 兼容上下文，保留旧的 state 访问习惯。"""

    @property
    def state(self) -> dict[str, Any]:
        state = self.context_vars
        state.setdefault("status", self.status.value)
        state.setdefault("plan_id", self.plan_id)
        return state

    @state.setter
    def state(self, value: dict[str, Any]) -> None:
        self.context_vars = value


class PlanSkillInvoker(Protocol):
    """PlanOrchestrator 使用的 Skill 调用协议。"""

    def invoke(self, skill_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        """调用指定 Skill 并返回结果。"""


class CallableSkillInvokerAdapter:
    """把旧式回调适配为正式 Skill 调用协议。"""

    def __init__(self, callback: Callable[[str, dict[str, Any], str | None], Any]) -> None:
        self._callback = callback

    def invoke(self, skill_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        return self._callback(skill_id, payload, idempotency_key)



class SkillManagerInvokerAdapter:
    """适配 shell.skill_manager.invoker.SkillInvoker 的最小调用协议。"""

    def __init__(self, invoker: Any) -> None:
        self._invoker = invoker

    def invoke(self, skill_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        self._invoker.ensure_circuit_closed(skill_id)
        call = getattr(self._invoker, "invoke", None)
        if not callable(call):
            raise A2PlanExecutionError("SkillInvoker.invoke is not implemented")
        try:
            try:
                result = call(skill_id, payload, idempotency_key=idempotency_key)
            except TypeError:
                result = call(skill_id, payload)
        except Exception:
            self._invoker.record_failure(skill_id)
            raise
        self._invoker.record_success(skill_id)
        return result


class PlanEventPublisher(Protocol):
    """任务事件发布协议。"""

    def publish(self, event_name: str, context: TaskContext, *, current_step: str | None = None) -> None:
        """发布任务事件。"""


class NullPlanEventPublisher:
    """空事件发布器，供纯内存测试与无 StateManager 场景使用。"""

    def publish(self, event_name: str, context: TaskContext, *, current_step: str | None = None) -> None:
        return None


class StateManagerPlanEventPublisher:
    """通过 StateManager task 域发布编排事件。"""

    def __init__(self, state_manager: StateManager, *, source: str = "plan_orchestrator") -> None:
        self._state_manager = state_manager
        self._source = source

    def publish(self, event_name: str, context: TaskContext, *, current_step: str | None = None) -> None:
        self._state_manager.publish_event(
            "task",
            event_name,
            {
                "trace_id": context.trace_id,
                "source": self._source,
                "version": 1,
                "data": {
                    "plan_id": context.plan_id,
                    "status": context.status.value,
                    "progress": context.progress,
                    "current_step": current_step or context.paused_step_id,
                    "paused_reason": context.paused_reason,
                    "error": context.error,
                    "step_error": context.step_errors.get(current_step or ""),
                },
            },
            source=self._source,
        )


class PlanStateStore(ABC):
    """任务状态持久化抽象接口。"""

    @abstractmethod
    def save(self, plan_id: str, context: TaskContext) -> None:
        """保存全量任务快照。"""

    @abstractmethod
    def load(self, plan_id: str) -> TaskContext | None:
        """加载全量任务快照。"""


class StateManagerPlanStore(PlanStateStore):
    """基于 StateManager 的任务快照存储适配器。"""

    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    def save(self, plan_id: str, context: TaskContext) -> None:
        self._state_manager.set_task_state(f"plan.{plan_id}.snapshot", context.to_snapshot())

    def load(self, plan_id: str) -> TaskContext | None:
        raw = self._state_manager.get_task_state(f"plan.{plan_id}.snapshot")
        if not raw:
            return None
        return TaskContext.from_snapshot(raw)


class InMemoryPlanStore(PlanStateStore):
    """测试与临时运行使用的内存快照存储。"""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}

    def save(self, plan_id: str, context: TaskContext) -> None:
        self._snapshots[plan_id] = context.to_snapshot()

    def load(self, plan_id: str) -> TaskContext | None:
        raw = self._snapshots.get(plan_id)
        if raw is None:
            return None
        return TaskContext.from_snapshot(raw)


class PlanEngine:
    """纯逻辑 DAG 编排引擎，无存储、无业务交互。"""

    @staticmethod
    def validate_dag(steps: Mapping[str, PlanStep]) -> None:
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
        return isinstance(error, DEFAULT_RETRYABLE_ERRORS)

    def run_until_blocked(
        self,
        context: TaskContext,
        step_executor: Callable[[PlanStep, dict[str, Any]], Any],
        *,
        sleep_fn: Callable[[float], None] | None = None,
        max_steps: int | None = None,
    ) -> TaskContext:
        if context.is_terminal():
            return context
        context._rebuild_dependency_satisfied_set()
        context.status = PlanStatus.RUNNING
        context.mark_started()
        context.paused_reason = None
        context.paused_step_id = None
        sleeper = sleep_fn or (lambda seconds: None)
        steps_executed = 0

        while True:
            ready_steps = context.get_ready_steps()
            if not ready_steps:
                if self._all_steps_final(context):
                    context.status = PlanStatus.DONE
                    context.mark_terminal()
                elif self._all_dependencies_failed(context):
                    failed_deps = self._collect_first_failed_deps(context)
                    context.status = PlanStatus.FAILED
                    context.error = f"upstream dependencies failed: {', '.join(failed_deps)}"
                    for step_id in context.steps:
                        if context.step_status.get(step_id) not in FINAL_STEP_STATUSES:
                            context.step_status[step_id] = StepStatus.CANCELLED
                            context.mark_step_completed(step_id)
                            context.mark_processed(step_id)
                    context.mark_terminal()
                else:
                    context.status = PlanStatus.PAUSED
                    context.paused_reason = "waiting_dependencies"
                    context.touch()
                break

            step = ready_steps[0]
            if step.require_consent and context.step_status.get(step.step_id) is not StepStatus.READY:
                context.status = PlanStatus.PAUSED
                context.paused_reason = "waiting_consent"
                context.paused_step_id = step.step_id
                context.step_status[step.step_id] = StepStatus.BLOCKED
                context.touch()
                break

            if not self._check_condition(step, context.context_vars):
                context.step_status[step.step_id] = StepStatus.SKIPPED
                context.mark_step_completed(step.step_id)
                self._mark_completed(context, step.step_id)
                continue

            result, error = self._execute_with_retry(step, context, step_executor, sleep_fn=sleeper)
            steps_executed += 1
            if error is not None:
                if step.degrade_value is not None:
                    context.step_status[step.step_id] = StepStatus.DEGRADED
                    context.set_step_result(step.step_id, step.degrade_value)
                    context.step_errors[step.step_id] = str(error)
                    context.mark_step_completed(step.step_id)
                    self._mark_completed(context, step.step_id)
                    if max_steps is not None and steps_executed >= max_steps:
                        if self._all_steps_final(context):
                            context.status = PlanStatus.DONE
                            context.mark_terminal()
                        break
                    continue
                context.step_status[step.step_id] = StepStatus.FAILED
                context.step_errors[step.step_id] = str(error)
                context.mark_step_completed(step.step_id)
                context.mark_processed(step.step_id)
                if step.fail_fast:
                    context.status = PlanStatus.FAILED
                    context.error = str(error)
                    context.paused_step_id = step.step_id
                    context.mark_terminal()
                    break
                if max_steps is not None and steps_executed >= max_steps:
                    break
                continue

            context.step_status[step.step_id] = StepStatus.DONE
            context.set_step_result(step.step_id, result)
            context.mark_step_completed(step.step_id)
            self._mark_completed(context, step.step_id)
            if max_steps is not None and steps_executed >= max_steps:
                if self._all_steps_final(context):
                    context.status = PlanStatus.DONE
                    context.mark_terminal()
                break

        return context

    def _execute_with_retry(
        self,
        step: PlanStep,
        context: TaskContext,
        step_executor: Callable[[PlanStep, dict[str, Any]], Any],
        *,
        sleep_fn: Callable[[float], None],
    ) -> tuple[Any, Exception | None]:
        attempts = 0
        while attempts <= step.retry_max:
            attempts += 1
            context.step_attempts[step.step_id] = attempts
            context.step_status[step.step_id] = StepStatus.RUNNING
            context.mark_step_started(step.step_id)
            try:
                return step_executor(step, context.context_vars), None
            except Exception as exc:
                if attempts >= step.retry_max or not self.is_retryable(exc):
                    return None, exc
                if step.retry_backoff_s > 0:
                    sleep_fn(step.retry_backoff_s)
        return None, RuntimeError("unreachable retry state")

    def _check_condition(self, step: PlanStep, context_vars: Mapping[str, Any]) -> bool:
        if not step.condition_key:
            return True
        return bool(context_vars.get(step.condition_key))

    def _all_steps_final(self, context: TaskContext) -> bool:
        return all(context.step_status.get(step_id) in FINAL_STEP_STATUSES for step_id in context.steps)

    def _all_dependencies_failed(self, context: TaskContext) -> bool:
        pending = [
            step for step_id, step in context.steps.items()
            if context.step_status.get(step_id) not in FINAL_STEP_STATUSES
        ]
        return bool(pending) and all(context.dependency_failed(step) for step in pending)

    def _collect_first_failed_deps(self, context: TaskContext) -> list[str]:
        failed_set: set[str] = set()
        for step_id, status in context.step_status.items():
            if status in DEPENDENCY_FAILED_STATUSES:
                failed_set.add(step_id)
        return sorted(failed_set)[:3]

    def _mark_completed(self, context: TaskContext, step_id: str) -> None:
        status = context.step_status.get(step_id)
        if status in DEPENDENCY_SATISFIED_STATUSES:
            context.mark_dependency_satisfied(step_id)
        else:
            context.mark_processed(step_id)


class PlanOrchestrator:
    """PlanEngine 门面，负责模板、存储、Skill 与 Consent 对接。"""

    def __init__(
        self,
        store: PlanStateStore | StateManager,
        templates_dir: str | Path | None = None,
        *,
        skill_invoker: PlanSkillInvoker | Callable[[str, dict[str, Any], str | None], Any] | None = None,
        consent_callback: Callable[[str, PlanStep], bool] | None = None,
        consent_adapter: ConsentAdapter | None = None,
        consent_gateway: Any | None = None,
        event_publisher: PlanEventPublisher | None = None,
        llm_backend: Any | None = None,
        hard_gate: Any | None = None,
        skill_tracker: Any | None = None,
        skill_resolver: Callable[[str], tuple[str | None, list[str]]] | None = None,
        subagent_scheduler: SubagentScheduler | None = None,
        privacy_mode: str = "local_only",
    ) -> None:
        if isinstance(store, StateManager):
            self._store: PlanStateStore = StateManagerPlanStore(store)
            self._event_publisher = event_publisher or StateManagerPlanEventPublisher(store)
        else:
            self._store = store
            self._event_publisher = event_publisher or NullPlanEventPublisher()
        self._engine = PlanEngine()
        self._skill_invoker = self._normalize_skill_invoker(skill_invoker)
        self._fallback_controller = None
        self._routed_invoker = None
        self._consent_callback = consent_callback
        self._consent_adapter = consent_adapter
        self.consent_gateway = consent_gateway
        self._llm_backend = llm_backend
        self._hard_gate = hard_gate
        self._skill_tracker = skill_tracker
        self._skill_resolver = skill_resolver
        self._subagent_scheduler = subagent_scheduler
        self._privacy_mode = privacy_mode
        self._skill_name: str | None = None
        self._skill_stages: list[str] = []
        default_templates_dir = Path(__file__).resolve().parents[3] / "configs" / "plans"
        self._templates_dir = Path(templates_dir) if templates_dir is not None else default_templates_dir

    def _normalize_skill_invoker(
        self,
        skill_invoker: PlanSkillInvoker | Callable[[str, dict[str, Any], str | None], Any] | None,
    ) -> PlanSkillInvoker | None:
        if skill_invoker is None:
            return None
        if hasattr(skill_invoker, "invoke"):
            return skill_invoker  # type: ignore[return-value]
        return CallableSkillInvokerAdapter(skill_invoker)

    def create_context(self, plan_id: str) -> PlanContext:
        return PlanContext(plan_id=plan_id)

    def _default_step_status(self, step_id: str) -> StepStatus:
        return StepStatus.PENDING

    def attach_fallback_controller(self, controller: Any) -> None:
        self._fallback_controller = controller

    def attach_routed_invoker(self, routed_invoker: Any) -> None:
        self._routed_invoker = routed_invoker

    def decide(self, user_input: str) -> list[PlanStep]:
        """摘要：使用 v1 本地规则将用户目标拆解为可执行计划步骤。

        参数：
            user_input: 用户提交的完整目标文本。

        返回值：
            满足 DAG 依赖关系的 ``PlanStep`` 列表；空输入返回空列表。
        """
        goal = (user_input or "").strip()
        if not goal:
            return []
        self._resolve_skill(goal)
        raw_steps: list[dict[str, Any]] | None = None
        if self._llm_backend is not None:
            from offline_companion.core.llm_decomposer import decompose_with_llm

            raw_steps = decompose_with_llm(
                goal,
                self._llm_backend,
                skill_stages=self._skill_stages or None,
                skill_name=self._skill_name,
            )
        if raw_steps is None:
            raw_steps = _rule_decompose(goal)
        return [
            self._raw_to_plan_step(step, goal, idx)
            for idx, step in enumerate(raw_steps)
        ]

    def _resolve_skill(self, user_input: str) -> None:
        """摘要：解析当前计划匹配的 Prompt Skill 及阶段序列。"""
        if self._skill_resolver is None:
            self._skill_name = None
            self._skill_stages = []
            return
        try:
            skill_name, stages = self._skill_resolver(user_input)
        except (OSError, RuntimeError, ValueError):
            self._skill_name = None
            self._skill_stages = []
            return
        if skill_name and stages:
            self._skill_name = str(skill_name)
            self._skill_stages = [str(stage) for stage in stages if str(stage).strip()]
            return
        self._skill_name = None
        self._skill_stages = []

    def _raw_to_plan_step(self, raw: Mapping[str, Any], user_input: str, idx: int) -> PlanStep:
        """摘要：将 LLM 或规则模板产出的字典转换为强类型计划步骤。"""
        step_id = str(raw.get("step_id") or f"step_{idx}")
        risk = str(raw.get("risk") or "low")
        title = str(raw.get("title") or raw.get("description") or step_id)
        description = str(raw.get("description") or title)
        expected_output = str(raw.get("expected_output") or "")
        verification = str(raw.get("verification") or "")
        completion_criteria = str(raw.get("completion_criteria") or "")
        estimated_minutes = _safe_non_negative_int(raw.get("estimated_minutes"))
        files = tuple(str(path) for path in raw.get("files", ()) or ())
        return PlanStep(
            step_id=step_id,
            skill_id=str(raw.get("skill_id") or "chat"),
            result_key=str(raw.get("result_key") or f"{step_id}_result"),
            depends_on=_normalize_raw_dependencies(raw, idx),
            condition_key=str(raw["condition_key"]) if raw.get("condition_key") is not None else None,
            retry_max=_safe_non_negative_int(raw.get("retry_max")),
            require_consent=bool(raw.get("require_consent", risk == "high")),
            payload={
                "description": title,
                "query": user_input,
                "risk": risk,
                "complexity": 7 if risk in {"medium", "high"} else 2,
                "expected_output": expected_output,
                "verification": verification,
                "completion_criteria": completion_criteria,
                "stage": raw.get("stage") or None,
                "estimated_minutes": estimated_minutes,
                "files": list(files),
            },
            title=title,
            description=description,
            expected_output=expected_output,
            verification=verification,
            completion_criteria=completion_criteria,
            stage=str(raw["stage"]) if raw.get("stage") else None,
            estimated_minutes=estimated_minutes,
            files=files,
            subagent_type=_normalize_subagent_role(raw.get("subagent_type")),
        )

    def load_template(self, plan_id: str) -> list[PlanStep]:
        for candidate in (
            self._templates_dir / f"{plan_id}.json",
            self._templates_dir / f"{plan_id}.yaml",
            self._templates_dir / f"{plan_id}.yml",
        ):
            if not candidate.is_file():
                continue
            raw = self._load_raw_template(candidate)
            return [self._parse_step(item, idx) for idx, item in enumerate(raw or [])]
        raise PlanTemplateNotFoundError(f"plan template {plan_id!r} not found in {self._templates_dir}")

    def create_plan(self, plan_id: str, steps: list[PlanStep]) -> TaskContext:
        """摘要：创建并持久化待执行计划，但不推进任何步骤。

        参数：
            plan_id: 计划唯一 ID。
            steps: 已拆解的计划步骤列表。

        返回值：
            状态为 ``pending`` 的计划上下文，可由后续执行入口恢复并推进。
        """
        step_map = {step.step_id: step for step in steps}
        self._engine.validate_dag(step_map)
        context = PlanContext(
            plan_id=plan_id,
            steps=step_map,
            step_status={step.step_id: StepStatus.PENDING for step in steps},
        )
        context.touch()
        self._store.save(plan_id, context)
        self._event_publisher.publish("task.plan_created", context)
        return context

    def start(self, plan_id: str, steps: list[PlanStep]) -> TaskContext:
        step_map = {step.step_id: step for step in steps}
        self._engine.validate_dag(step_map)
        context = PlanContext(
            plan_id=plan_id,
            steps=step_map,
            step_status={step.step_id: StepStatus.PENDING for step in steps},
        )
        context.touch()
        self._store.save(plan_id, context)
        self._event_publisher.publish("task.plan_started", context)
        return self._run(context)

    def resume(self, plan_id: str, *, consent_granted: bool | None = None) -> TaskContext:
        context = self._store.load(plan_id)
        if context is None or context.is_terminal():
            raise A2PlanValidationError(f"plan {plan_id!r} cannot be resumed")
        if context.status is PlanStatus.PAUSED and context.paused_reason == "waiting_consent":
            paused_step_id = context.paused_step_id
            if paused_step_id is not None:
                consent_payload = context.get_step_consent_request(paused_step_id)
                if consent_payload is not None:
                    context.set_step_consent_request(paused_step_id, consent_payload)
            if consent_granted is True and paused_step_id is not None:
                context.step_status[paused_step_id] = StepStatus.READY
                context.paused_reason = None
                context.paused_step_id = None
                context.touch()
            elif consent_granted is False and paused_step_id is not None:
                context.step_status[paused_step_id] = StepStatus.CANCELLED
                context.mark_step_completed(paused_step_id)
                context.mark_processed(paused_step_id)
                context.status = PlanStatus.CANCELLED
                context.mark_terminal()
                self._store.save(plan_id, context)
                self._event_publisher.publish("task.plan_cancelled", context, current_step=paused_step_id)
                return context
        context.touch()
        self._store.save(plan_id, context)
        self._event_publisher.publish("task.plan_resumed", context)
        return self._run(context)

    def load_context(self, plan_id: str) -> PlanContext | None:
        """摘要：从持久化存储加载计划，并统一恢复为 ``PlanContext``。"""
        context = self._store.load(plan_id)
        if context is None:
            return None
        if isinstance(context, PlanContext):
            return context
        return PlanContext.from_snapshot(context.to_snapshot())

    def pause(self, plan_id: str, *, reason: str = "user_input") -> PlanContext | None:
        """摘要：协作式暂停非终态计划并持久化。

        参数：
            plan_id: 要暂停的计划 ID。
            reason: 暂停原因；IdleThink 用户中断使用 ``user_input``。

        返回值：
            已暂停的计划上下文；计划不存在时返回 ``None``。
        """
        context = self.load_context(plan_id)
        if context is None:
            return None
        if context.is_terminal():
            return context
        context.status = PlanStatus.PAUSED
        context.paused_reason = reason
        context.paused_step_id = None
        context.touch()
        self._store.save(plan_id, context)
        self._event_publisher.publish("task.plan_paused", context)
        return context

    def cancel(self, plan_id: str) -> None:
        context = self._store.load(plan_id)
        if context is None:
            raise A2PlanValidationError(f"plan {plan_id!r} not found")
        context.status = PlanStatus.CANCELLED
        for step_id, status in list(context.step_status.items()):
            if status not in FINAL_STEP_STATUSES:
                context.step_status[step_id] = StepStatus.CANCELLED
                context.mark_step_completed(step_id)
                context.mark_processed(step_id)
        context.mark_terminal()
        self._store.save(plan_id, context)
        self._event_publisher.publish("task.plan_cancelled", context)

    def execute_plan(
        self,
        plan_id: str,
        *,
        invoke_skill: Callable[[PlanStep, TaskContext], Any] | None = None,
        context: TaskContext | None = None,
    ) -> TaskContext:
        """兼容旧接口；迁移期保留，非并发安全，新代码应使用 start/resume/cancel。"""
        steps = self.load_template(plan_id) if context is None or not context.steps else list(context.steps.values())
        if context is None:
            context = PlanContext(
                plan_id=plan_id,
                steps={step.step_id: step for step in steps},
                step_status={step.step_id: StepStatus.PENDING for step in steps},
            )
        elif not context.steps:
            context.steps = {step.step_id: step for step in steps}
            context.step_status = {step.step_id: StepStatus.PENDING for step in steps}
        if invoke_skill is not None:
            def legacy_invoker(skill_id: str, payload: dict[str, Any], idempotency_key: str | None) -> Any:
                running_step = next(
                    step for step_id, step in context.steps.items()
                    if step.skill_id == skill_id and context.step_status.get(step_id) is StepStatus.RUNNING
                )
                return invoke_skill(running_step, context)

            self._skill_invoker = CallableSkillInvokerAdapter(legacy_invoker)
        return self._run(context)

    def _run(self, context: TaskContext) -> TaskContext:
        if not context.steps:
            context.status = PlanStatus.DONE
            context.mark_started()
            context.mark_terminal()
            self._store.save(context.plan_id, context)
            return context

        fallback_chain = tuple(context.context_vars.get("fallback_chain", []) or ())
        if fallback_chain and "route_mode" not in context.context_vars:
            context.context_vars["route_mode"] = fallback_chain[0]
            context.context_vars["fallback_index"] = 0
            context.touch()

        def executor(step: PlanStep, context_vars: dict[str, Any]) -> Any:
            if self._routed_invoker is not None:
                return self._routed_invoker.invoke_step(step, context)
            if self._skill_invoker is None:
                raise A2PlanExecutionError("skill_invoker is required")
            payload = dict(step.payload)
            if context_vars.get("route_mode") is not None:
                payload["_route_mode"] = context_vars.get("route_mode")
            if context_vars.get("fallback_chain") is not None:
                payload["_fallback_chain"] = list(context_vars.get("fallback_chain") or [])
            if context_vars.get("fallback_index") is not None:
                payload["_fallback_index"] = int(context_vars.get("fallback_index") or 0)
            return self._skill_invoker.invoke(step.skill_id, payload, step.idempotency_key)

        context = self._engine.run_until_blocked(context, executor, sleep_fn=sleep)
        if context.status is PlanStatus.FAILED and context.context_vars.get("fallback_chain") and self._fallback_controller is not None:
            failed_step = context.paused_step_id or next((sid for sid, status in context.step_status.items() if status is StepStatus.FAILED), None)
            if self._fallback_controller.advance(context, reason=context.error or "step_failed", step_id=failed_step, error=context.error):
                context.status = PlanStatus.RUNNING
                context.error = None
                context.completed_at = None
                context.touch()
                self._store.save(context.plan_id, context)
                return self._run(context)
        step_events = self._collect_step_events(context)
        plan_events = self._collect_plan_events(context)
        if context.status is PlanStatus.PAUSED and context.paused_reason == "waiting_consent" and context.paused_step_id:
            context.context_vars.setdefault("requires_consent", True)
            context.touch()
        if context.status is PlanStatus.PAUSED and context.paused_reason == "waiting_consent":
            self._prepare_consent_pause(context)
        # 状态是唯一真值源：先落盘，再发通知；避免下游收到事件后快照仍是旧值。
        self._store.save(context.plan_id, context)
        for event_name, step_id in step_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        for event_name, step_id in plan_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        return context

    def execute_next(
        self,
        context: PlanContext,
        *,
        invoke_skill: Callable[[PlanStep, TaskContext], Any] | None = None,
    ) -> PlanContext:
        """摘要：执行至多一个 DAG 步骤，供 SSE 编排器逐步推进计划。"""
        if context.is_terminal():
            return context
        if context.status is PlanStatus.PAUSED and context.paused_reason == "hard_gate_blocked":
            return context
        if invoke_skill is not None:
            def legacy_invoker(skill_id: str, payload: dict[str, Any], idempotency_key: str | None) -> Any:
                del payload, idempotency_key
                running_step = next(
                    step
                    for step_id, step in context.steps.items()
                    if step.skill_id == skill_id and context.step_status.get(step_id) is StepStatus.RUNNING
                )
                return invoke_skill(running_step, context)

            self._skill_invoker = CallableSkillInvokerAdapter(legacy_invoker)
        self._ensure_plan_skill_context(context)
        gate_blocked = self._block_on_hard_gate_if_needed(context)
        if gate_blocked:
            self._store.save(context.plan_id, context)
            self._event_publisher.publish("task.plan_blocked", context, current_step=context.paused_step_id)
            return context

        def executor(step: PlanStep, context_vars: dict[str, Any]) -> Any:
            session_id, skill_name = self._gate_identity(context)
            self._start_tracked_stage(session_id, skill_name, step)
            try:
                if step.subagent_type is not None and self._subagent_scheduler is not None:
                    ctx = self._subagent_scheduler.spawn(
                        parent_session_id=session_id,
                        role=step.subagent_type,
                        task_description=step.description or step.title,
                        allowed_files=list(step.files),
                        privacy_mode=str(context_vars.get("privacy_mode") or self._privacy_mode or "local_only"),
                        plan_id=context.plan_id,
                        step_id=step.step_id,
                    )
                    result = self._subagent_scheduler.run(ctx)
                    result_payload = dataclasses.asdict(result)
                    result_payload["subagent_role"] = step.subagent_type
                    result = result_payload
                elif self._routed_invoker is not None:
                    result = self._routed_invoker.invoke_step(step, context)
                else:
                    if self._skill_invoker is None:
                        raise A2PlanExecutionError("skill_invoker is required")
                    payload = dict(step.payload)
                    if context_vars.get("route_mode") is not None:
                        payload["_route_mode"] = context_vars.get("route_mode")
                    if context_vars.get("fallback_chain") is not None:
                        payload["_fallback_chain"] = list(context_vars.get("fallback_chain") or [])
                    if context_vars.get("fallback_index") is not None:
                        payload["_fallback_index"] = int(context_vars.get("fallback_index") or 0)
                    result = self._skill_invoker.invoke(step.skill_id, payload, step.idempotency_key)
            except (A2PlanExecutionError, KeyError, RuntimeError, TimeoutError, ConnectionError, ValueError) as exc:
                self._fail_tracked_stage(session_id, skill_name, step, str(exc))
                raise
            self._complete_tracked_stage(session_id, skill_name, step, result)
            return result

        context = self._engine.run_until_blocked(context, executor, sleep_fn=sleep, max_steps=1)
        while (
            context.status is PlanStatus.FAILED
            and context.context_vars.get("fallback_chain")
            and self._fallback_controller is not None
        ):
            failed_step_id = context.paused_step_id or next(
                (step_id for step_id, status in context.step_status.items() if status is StepStatus.FAILED),
                None,
            )
            if failed_step_id is None or not self._fallback_controller.advance(
                context,
                reason=context.error or "step_failed",
                step_id=failed_step_id,
                error=context.error,
            ):
                break
            context.status = PlanStatus.RUNNING
            context.error = None
            context.completed_at = None
            context.touch()
            self._store.save(context.plan_id, context)
            context = self._engine.run_until_blocked(context, executor, sleep_fn=sleep, max_steps=1)

        if context.paused_reason == "waiting_consent" and context.paused_step_id:
            self._prepare_consent_pause(context)
        step_events = self._collect_step_events(context)
        plan_events = self._collect_plan_events(context)
        self._store.save(context.plan_id, context)
        for event_name, step_id in step_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        for event_name, step_id in plan_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        return context

    def apply_consent_decision(self, context: PlanContext, request_id: str) -> PlanContext:
        """摘要：验证 A3 已落定的审批结果，并安全更新暂停计划。"""
        step_id = context.paused_step_id
        if context.paused_reason != "waiting_consent" or step_id is None:
            raise A2PlanValidationError("plan is not waiting for consent")
        consent_payload = context.get_step_consent_request(step_id) or {}
        if str(consent_payload.get("request_id") or "") != request_id:
            raise A2PlanValidationError("consent request does not match paused plan")
        pending = self.consent_gateway.get_pending(request_id) if self.consent_gateway is not None else None
        if pending is None or not pending.decided:
            raise A2PlanValidationError("consent request has not been decided")
        if pending.allowed:
            context.step_status[step_id] = StepStatus.READY
            context.paused_reason = None
            context.paused_step_id = None
            context.status = PlanStatus.RUNNING
            context.context_vars["requires_consent"] = False
            context.touch()
        else:
            context.step_status[step_id] = StepStatus.CANCELLED
            context.mark_step_completed(step_id)
            context.mark_processed(step_id)
            context.status = PlanStatus.CANCELLED
            context.mark_terminal()
        self._store.save(context.plan_id, context)
        return context

    def _prepare_consent_pause(self, context: TaskContext) -> None:
        """摘要：登记真实 A3 请求标识并持久化步骤级 Consent 上下文。"""
        step_id = context.paused_step_id
        if not step_id:
            return
        consent_payload = context.get_step_consent_request(step_id)
        if consent_payload is None:
            consent_request = self._build_consent_request(context, context.steps[step_id])
            consent_payload = dataclasses.asdict(consent_request)
        route_decision = context.get_step_route_decision(step_id)
        if route_decision is None:
            legacy_route_decision = context.get_context_var("route_decision")
            if isinstance(legacy_route_decision, dict):
                route_decision = dict(legacy_route_decision)
        if route_decision is not None:
            context.set_step_route_decision(step_id, route_decision)
        if not consent_payload.get("request_id"):
            consent_request = self._build_consent_request(context, context.steps[step_id])
            if self._consent_adapter is not None:
                context.context_vars["consent_requested"] = self._consent_adapter.request(consent_request)
                artifact = getattr(self.consent_gateway, "last_artifact", None) or {}
                consent_payload["request_id"] = artifact.get("request_id")
            elif self._consent_callback is not None:
                context.context_vars["consent_requested"] = self._consent_callback(
                    context.plan_id,
                    context.steps[step_id],
                )
            consent_payload.setdefault("request_id", str(uuid4()))
        context.set_step_consent_request(step_id, consent_payload)
        context.context_vars.setdefault("requires_consent", True)
        context.touch()
        self._store.save(context.plan_id, context)
        self._event_publisher.publish("task.consent_request", context, current_step=step_id)

    def _ensure_plan_skill_context(self, context: TaskContext) -> None:
        """摘要：把当前匹配 Skill 写入计划上下文，供恢复与门禁复用。"""
        if self._skill_name and self._skill_stages:
            context.context_vars.setdefault("skill_name", self._skill_name)
            context.context_vars.setdefault("skill_stages", list(self._skill_stages))
            return
        raw_name = context.context_vars.get("skill_name")
        raw_stages = context.context_vars.get("skill_stages")
        if raw_name and isinstance(raw_stages, list):
            self._skill_name = str(raw_name)
            self._skill_stages = [str(stage) for stage in raw_stages if str(stage).strip()]

    def _block_on_hard_gate_if_needed(self, context: TaskContext) -> bool:
        """摘要：在执行下一个 ready step 前检查 Skill 阶段硬门禁。"""
        if self._hard_gate is None:
            return False
        ready_steps = context.get_ready_steps()
        if not ready_steps:
            return False
        step = ready_steps[0]
        if not step.stage:
            return False
        session_id, skill_name = self._gate_identity(context)
        if not skill_name:
            return False
        stages = self._gate_stages(context)
        gate = self._hard_gate.check(session_id, skill_name, step.stage, stages)
        if gate.get("allowed") is True:
            return False
        missing = [str(item) for item in gate.get("missing", [])] if isinstance(gate.get("missing"), list) else []
        context.step_status[step.step_id] = StepStatus.BLOCKED
        context.paused_reason = "hard_gate_blocked"
        context.paused_step_id = step.step_id
        context.error = str(gate.get("reason") or "hard_gate_blocked")
        context.context_vars["hard_gate"] = {
            "skill_name": skill_name,
            "stage": step.stage,
            "missing_stages": missing,
            "reason": context.error,
        }
        context.status = PlanStatus.PAUSED
        context.touch()
        return True

    def _gate_identity(self, context: TaskContext) -> tuple[str, str | None]:
        """摘要：返回当前计划的可信 session_id 与 Skill 名称。"""
        session_id = str(context.context_vars.get("session_id") or context.plan_id or "default").strip() or "default"
        skill_name = str(context.context_vars.get("skill_name") or self._skill_name or "").strip() or None
        return session_id, skill_name

    def _gate_stages(self, context: TaskContext) -> list[str]:
        """摘要：返回当前计划声明的 Skill 阶段序列。"""
        raw = context.context_vars.get("skill_stages")
        if isinstance(raw, list):
            return [str(stage) for stage in raw if str(stage).strip()]
        return list(self._skill_stages)

    def _start_tracked_stage(self, session_id: str, skill_name: str | None, step: PlanStep) -> None:
        """摘要：执行前记录阶段开始状态。"""
        if self._skill_tracker is None or not skill_name or not step.stage:
            return
        self._skill_tracker.start_stage(session_id, skill_name, step.stage)

    def _complete_tracked_stage(
        self,
        session_id: str,
        skill_name: str | None,
        step: PlanStep,
        result: Any,
    ) -> None:
        """摘要：执行成功后保存阶段完成证据。"""
        if self._skill_tracker is None or not skill_name or not step.stage:
            return
        evidence = _stage_evidence(step, result)
        self._skill_tracker.complete_stage(session_id, skill_name, step.stage, evidence)

    def _fail_tracked_stage(self, session_id: str, skill_name: str | None, step: PlanStep, reason: str) -> None:
        """摘要：执行失败后保存阶段失败原因。"""
        if self._skill_tracker is None or not skill_name or not step.stage:
            return
        self._skill_tracker.fail_stage(session_id, skill_name, step.stage, reason)

    def _build_consent_request(self, context: TaskContext, step: PlanStep) -> ConsentRequest:
        return ConsentRequest(
            plan_id=context.plan_id,
            step_id=step.step_id,
            skill_id=step.skill_id,
            operation="execute_step",
            purpose_type=PurposeType.PLUGIN_HIGH_RISK_SKILL if step.require_consent else PurposeType.SKILL_INVOKE,
            risk_level="high" if step.require_consent else "medium",
            impact_scope="plan_step",
            metadata={
                "result_key": step.result_key,
                "depends_on": list(step.depends_on),
                "retry_max": step.retry_max,
            },
        )

    def _collect_step_events(self, context: TaskContext) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        published = set(context.published_step_events)
        for step_id in context.processed_steps:
            if step_id in published:
                continue
            status = context.step_status.get(step_id)
            if status is StepStatus.DONE:
                events.append(("task.step_completed", step_id))
            elif status is StepStatus.FAILED:
                events.append(("task.step_failed", step_id))
            elif status is StepStatus.DEGRADED:
                events.append(("task.step_degraded", step_id))
            else:
                continue
            context.published_step_events.append(step_id)
            published.add(step_id)
        return events

    def _collect_plan_events(self, context: TaskContext) -> list[tuple[str, str | None]]:
        if context.status is PlanStatus.PAUSED and context.paused_reason == "waiting_consent":
            return [("task.plan_paused", context.paused_step_id)]
        if context.status is PlanStatus.DONE:
            return [("task.plan_completed", None)]
        if context.status is PlanStatus.FAILED:
            return [("task.plan_failed", None)]
        return []

    def _load_raw_template(self, path: Path) -> Any:
        content = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(content)
        try:
            import yaml
        except Exception as exc:  # pragma: no cover - dependency guard
            raise A2PlanExecutionError("PyYAML is required to load YAML plan templates") from exc
        return yaml.safe_load(content)

    def _parse_step(self, item: Mapping[str, Any], idx: int) -> PlanStep:
        depends_on = tuple(item.get("depends_on", []) or ())
        if isinstance(item.get("depends_on"), str):
            depends_on = (str(item["depends_on"]),)
        return PlanStep(
            step_id=str(item.get("step_id", f"step-{idx}")),
            skill_id=str(item["skill_id"]),
            result_key=str(item.get("result_key", item.get("skill_id", f"result_{idx}"))),
            depends_on=depends_on,
            condition_key=item.get("condition_key") or item.get("condition_expr"),
            retry_max=max(0, int(item.get("retry_max", item.get("retry_count", 0)))),
            retry_backoff_s=max(0.0, float(item.get("retry_backoff_s", 0.0))),
            degrade_value=item.get("degrade_value", item.get("degrade_to")),
            require_consent=bool(item.get("require_consent", False)),
            idempotency_key=item.get("idempotency_key"),
            payload=dict(item.get("payload", {})),
            fail_fast=bool(item.get("fail_fast", True)),
            title=str(item.get("title") or item.get("payload", {}).get("description") or ""),
            description=str(item.get("description") or item.get("payload", {}).get("description") or ""),
            expected_output=str(item.get("expected_output") or ""),
            verification=str(item.get("verification") or ""),
            completion_criteria=str(item.get("completion_criteria") or ""),
            stage=str(item["stage"]) if item.get("stage") is not None else None,
            estimated_minutes=max(0, int(item.get("estimated_minutes", 0) or 0)),
            files=tuple(str(path) for path in item.get("files", ()) or ()),
            subagent_type=_normalize_subagent_role(item.get("subagent_type")),
        )


def _step_to_dict(step: PlanStep) -> dict[str, Any]:
    payload = dataclasses.asdict(step)
    payload["depends_on"] = list(step.depends_on)
    payload["files"] = list(step.files)
    return payload


def _normalize_raw_dependencies(raw: Mapping[str, Any], idx: int) -> tuple[str, ...]:
    """摘要：归一化 LLM 或规则模板中的依赖字段。"""
    del idx
    raw_deps = raw.get("depends_on", raw.get("deps", ())) or ()
    if isinstance(raw_deps, str):
        raw_deps = (raw_deps,)
    deps: list[str] = []
    for dep in raw_deps:
        if isinstance(dep, int):
            deps.append(f"step_{dep}")
            continue
        text = str(dep).strip()
        if not text:
            continue
        deps.append(f"step_{text}" if text.isdigit() else text)
    return tuple(deps)


def _safe_non_negative_int(value: Any) -> int:
    """摘要：将外部输入安全转换为非负整数。"""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _stage_evidence(step: PlanStep, result: Any) -> str:
    """摘要：从步骤结果和计划字段中提取阶段完成证据。"""
    if isinstance(result, Mapping):
        raw = result.get("evidence") or result.get("verification") or result.get("result")
        if raw:
            return str(raw)
    return step.verification or step.expected_output or "completed"


def _rule_decompose(goal: str) -> list[dict[str, Any]]:
    """摘要：按目标关键词生成 v1 串行步骤模板。"""
    if any(keyword in goal for keyword in ("写", "制作", "实现", "开发", "代码")):
        return [
            _rule_step(
                title="理解需求：解析目标功能与约束",
                description=f"分析用户请求「{goal}」，明确输入、输出、限制和验收口径。",
                expected_output="需求边界说明，包含输入、输出、约束和验收口径。",
                verification="检查需求边界说明是否覆盖输入、输出、约束和验收口径四项。",
                completion_criteria="四项信息均有具体描述，且没有仅复述用户原话。",
                stage="brainstorming",
                estimated_minutes=5,
            ),
            _rule_step(
                title="设计方案：确定模块边界与数据流",
                description=f"为「{goal}」确定需要修改的模块、数据流和最小实现路径。",
                expected_output="实现方案，包含涉及模块、数据流、风险点和测试策略。",
                verification="方案中列出至少一个涉及模块，并说明对应测试或检查方式。",
                completion_criteria="模块边界清楚，测试策略可执行，风险点有处理方式。",
                deps=(0,),
                stage="planning",
                estimated_minutes=10,
            ),
            _rule_step(
                title="实现核心逻辑：完成主要代码改动",
                description=f"按方案实现「{goal}」所需的核心代码，并保持现有架构边界。",
                expected_output="完成的代码改动，包含核心逻辑和必要的兼容处理。",
                verification="运行相关窄测试、静态检查或手动验证命令确认改动可用。",
                completion_criteria="核心路径可运行，相关验证通过，未引入无关重构。",
                deps=(1,),
                risk="medium",
                stage="tdd",
                estimated_minutes=30,
            ),
            _rule_step(
                title="运行验证：执行相关测试与检查",
                description=f"运行覆盖「{goal}」的最小测试集，并记录实际输出。",
                expected_output="测试或检查输出，包含 pass/fail 计数或明确的手动验证结果。",
                verification="确认输出中没有新增 failure，skip 项有合理说明。",
                completion_criteria="验证结果可追溯，失败项已修复或明确标记为无关问题。",
                deps=(2,),
                stage="review",
                estimated_minutes=10,
            ),
            _rule_step(
                title="整理交付：总结变更与后续风险",
                description=f"汇总「{goal}」的实现结果、验证结果和剩余风险。",
                expected_output="交付摘要，包含改动文件、验证命令和后续风险。",
                verification="摘要中包含至少一条验证证据，并列出无验证时的原因。",
                completion_criteria="用户可以根据摘要复查改动和验证结果。",
                deps=(3,),
                stage="finalize",
                estimated_minutes=5,
            ),
        ]
    if any(keyword in goal for keyword in ("部署", "安装", "下载", "网络", "权限")):
        return [
            _rule_step(
                title="检查环境：确认运行时、路径与权限",
                description=f"检查「{goal}」需要的运行时、文件路径、权限和隐私边界。",
                expected_output="环境检查记录，包含路径、权限、网络或出站需求。",
                verification="逐项确认环境检查记录中的前置条件是否满足。",
                completion_criteria="阻断项已列出，涉及出站或高风险操作已标明 consent 需求。",
                stage="brainstorming",
                estimated_minutes=5,
            ),
            _rule_step(
                title="准备依赖：下载或定位所需组件",
                description=f"准备「{goal}」所需依赖，优先使用本地已有资源。",
                expected_output="依赖清单及来源，包含本地路径或经过同意的下载来源。",
                verification="检查依赖文件存在、版本符合要求，或记录无法获取的原因。",
                completion_criteria="依赖来源可追溯，不存在未经同意的静默出站。",
                deps=(0,),
                risk="medium",
                stage="planning",
                estimated_minutes=15,
            ),
            _rule_step(
                title="执行变更：修改系统或服务配置",
                description=f"在授权范围内执行「{goal}」涉及的安装、部署或配置变更。",
                expected_output="完成的配置或部署变更记录。",
                verification="检查目标服务、文件或配置项达到预期状态。",
                completion_criteria="变更已完成，高风险步骤有 consent 证据，失败时保留错误信息。",
                deps=(1,),
                risk="high",
                stage="tdd",
                estimated_minutes=30,
            ),
            _rule_step(
                title="验证结果：检查服务状态与日志",
                description=f"验证「{goal}」完成后的服务状态、日志和回退风险。",
                expected_output="验证记录，包含状态检查、日志摘要和剩余风险。",
                verification="运行状态检查命令或读取日志，确认没有新增错误。",
                completion_criteria="关键服务或配置状态符合预期，异常已记录并给出处理建议。",
                deps=(2,),
                stage="finalize",
                estimated_minutes=10,
            ),
        ]
    if any(keyword in goal for keyword in ("分析", "研究", "评估", "梳理")):
        return [
            _rule_step(
                title="收集上下文：整理相关代码与数据",
                description=f"定位与「{goal}」相关的文件、数据、日志或文档。",
                expected_output="上下文清单，包含来源路径和关键片段摘要。",
                verification="确认清单中的来源可访问，且覆盖用户问题中的关键对象。",
                completion_criteria="上下文足以支持后续判断，没有明显遗漏的主路径。",
                stage="brainstorming",
                estimated_minutes=10,
            ),
            _rule_step(
                title="结构化分析：提取关键事实与差异",
                description=f"对「{goal}」相关上下文进行归类、对比和因果分析。",
                expected_output="结构化分析结果，包含事实、差异、风险和推论边界。",
                verification="每个关键结论都能追溯到上下文来源或明确标记为推论。",
                completion_criteria="事实与推论分离，风险项有优先级。",
                deps=(0,),
                stage="planning",
                estimated_minutes=20,
            ),
            _rule_step(
                title="输出结论：给出判断和建议路径",
                description=f"基于分析给出「{goal}」的结论、建议和下一步行动。",
                expected_output="结论摘要，包含建议路径、证据和未决问题。",
                verification="结论覆盖用户问题，并列出至少一项可执行下一步。",
                completion_criteria="建议可执行，证据充分，未决问题不被包装成事实。",
                deps=(1,),
                stage="finalize",
                estimated_minutes=10,
            ),
        ]
    return [
        _rule_step(
            title="确认任务边界：提取目标对象和约束",
            description=f"从「{goal}」中提取目标对象、约束、风险和需要用户确认的空缺。",
            expected_output="任务边界说明，包含目标对象、约束、风险和缺口。",
            verification="检查边界说明是否能回答谁、做什么、做到什么程度。",
            completion_criteria="目标对象明确，缺口不会阻止下一步最小推进。",
            stage="brainstorming",
            estimated_minutes=5,
        ),
        _rule_step(
            title="拆出可执行动作：形成最小步骤清单",
            description=f"将「{goal}」拆成可独立执行和验证的最小动作。",
            expected_output="步骤清单，至少包含动作、产出物、验证方式和依赖关系。",
            verification="检查每个步骤都有 expected_output、verification 和 completion_criteria。",
            completion_criteria="步骤不是元模板描述，且依赖关系清楚。",
            deps=(0,),
            stage="planning",
            estimated_minutes=10,
        ),
        _rule_step(
            title="完成首个可验证动作：产出最小结果",
            description=f"执行「{goal}」中最小且可验证的核心动作。",
            expected_output="首个可检查的任务结果或明确的阻断证据。",
            verification="按步骤定义的验证方式检查产出是否存在且符合约束。",
            completion_criteria="产出可被复查，失败时保留错误和下一步修复路径。",
            deps=(1,),
            risk="medium",
            stage="tdd",
            estimated_minutes=20,
        ),
        _rule_step(
            title="核对结果：记录验证证据和剩余风险",
            description=f"核对「{goal}」的执行结果，并记录验证证据、失败项和后续风险。",
            expected_output="验证摘要，包含实际结果、证据和剩余风险。",
            verification="确认验证摘要中包含真实检查结果，而不是主观判断。",
            completion_criteria="证据可追溯，剩余风险已清楚列出。",
            deps=(2,),
            stage="finalize",
            estimated_minutes=5,
        ),
    ]


def _rule_step(
    *,
    title: str,
    description: str,
    expected_output: str,
    verification: str,
    completion_criteria: str,
    deps: tuple[int, ...] = (),
    risk: str = "low",
    stage: str | None = None,
    estimated_minutes: int = 0,
    files: tuple[str, ...] = (),
) -> dict[str, Any]:
    """摘要：构造规则拆解步骤，确保 fallback 也满足强类型计划字段。"""
    return {
        "title": title,
        "description": description,
        "expected_output": expected_output,
        "verification": verification,
        "completion_criteria": completion_criteria,
        "deps": list(deps),
        "risk": risk,
        "stage": stage,
        "estimated_minutes": max(0, int(estimated_minutes)),
        "files": list(files),
    }


def _step_from_dict(payload: dict[str, Any]) -> PlanStep:
    payload["depends_on"] = tuple(payload.get("depends_on", []) or ())
    payload["files"] = tuple(str(path) for path in payload.get("files", ()) or ())
    payload["subagent_type"] = _normalize_subagent_role(payload.get("subagent_type"))
    if "condition_expr" in payload and "condition_key" not in payload:
        payload["condition_key"] = payload.pop("condition_expr")
    payload.pop("timeout_s", None)
    return PlanStep(**payload)


def _normalize_subagent_role(value: Any) -> SubagentRole | None:
    """摘要：归一化计划步骤中的子 Agent 角色字段。"""
    if value is None:
        return None
    text = str(value).strip()
    if text in {"implementer", "reviewer"}:
        return text  # type: ignore[return-value]
    return None


def _optional_float(value: Any) -> float | None:
    """摘要：将快照中的可选数值字段转为 float。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_dict(value: Any) -> dict[str, float]:
    """摘要：将快照中的时间戳字典转为 `dict[str, float]`。"""
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, float] = {}
    for key, item in value.items():
        parsed = _optional_float(item)
        if parsed is not None:
            out[str(key)] = parsed
    return out


def _dict_of_dict(value: Any) -> dict[str, dict[str, Any]]:
    """摘要：将快照中的嵌套字典安全转为结构化映射。"""
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            out[str(key)] = dict(item)
    return out
