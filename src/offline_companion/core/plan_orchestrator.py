"""plan_orchestrator：A2 任务规划与执行编排。"""

from __future__ import annotations

import dataclasses
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import sleep
from typing import Any, Protocol
from uuid import uuid4

from offline_companion.core.state_manager import StateManager
from offline_companion.shared.errors import (
    A2PlanExecutionError,
    A2PlanTemplateNotFoundError,
    A2PlanValidationError,
)


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
    """单个规划步骤的静态定义。"""

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


@dataclass
class TaskContext:
    """任务唯一真值源，可全量快照持久化。"""

    plan_id: str
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
            "progress": self.progress,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> TaskContext:
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
        )


class PlanTemplateNotFoundError(A2PlanTemplateNotFoundError):
    """指定计划模板不存在。"""


@dataclass(frozen=True)
class ConsentRequest:
    """结构化 Consent 请求。"""

    plan_id: str
    step_id: str
    skill_id: str
    operation: str
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
    ) -> TaskContext:
        if context.is_terminal():
            return context
        context._rebuild_dependency_satisfied_set()
        context.status = PlanStatus.RUNNING
        context.paused_reason = None
        context.paused_step_id = None
        sleeper = sleep_fn or (lambda seconds: None)

        while True:
            ready_steps = context.get_ready_steps()
            if not ready_steps:
                if self._all_steps_final(context):
                    context.status = PlanStatus.DONE
                elif self._all_dependencies_failed(context):
                    failed_deps = self._collect_first_failed_deps(context)
                    context.status = PlanStatus.FAILED
                    context.error = f"upstream dependencies failed: {', '.join(failed_deps)}"
                    for step_id in context.steps:
                        if context.step_status.get(step_id) not in FINAL_STEP_STATUSES:
                            context.step_status[step_id] = StepStatus.CANCELLED
                            context.mark_processed(step_id)
                else:
                    context.status = PlanStatus.PAUSED
                    context.paused_reason = "waiting_dependencies"
                break

            step = ready_steps[0]
            if step.require_consent and context.step_status.get(step.step_id) is not StepStatus.READY:
                context.status = PlanStatus.PAUSED
                context.paused_reason = "waiting_consent"
                context.paused_step_id = step.step_id
                context.step_status[step.step_id] = StepStatus.BLOCKED
                break

            if not self._check_condition(step, context.context_vars):
                context.step_status[step.step_id] = StepStatus.SKIPPED
                self._mark_completed(context, step.step_id)
                continue

            result, error = self._execute_with_retry(step, context, step_executor, sleep_fn=sleeper)
            if error is not None:
                if step.degrade_value is not None:
                    context.step_status[step.step_id] = StepStatus.DEGRADED
                    context.step_results[step.result_key] = step.degrade_value
                    context.context_vars[step.result_key] = step.degrade_value
                    context.step_errors[step.step_id] = str(error)
                    self._mark_completed(context, step.step_id)
                    continue
                context.step_status[step.step_id] = StepStatus.FAILED
                context.step_errors[step.step_id] = str(error)
                context.mark_processed(step.step_id)
                if step.fail_fast:
                    context.status = PlanStatus.FAILED
                    context.error = str(error)
                    context.paused_step_id = step.step_id
                    break
                continue

            context.step_status[step.step_id] = StepStatus.DONE
            context.step_results[step.result_key] = result
            context.context_vars[step.result_key] = result
            self._mark_completed(context, step.step_id)

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

    def start(self, plan_id: str, steps: list[PlanStep]) -> TaskContext:
        step_map = {step.step_id: step for step in steps}
        self._engine.validate_dag(step_map)
        context = PlanContext(
            plan_id=plan_id,
            steps=step_map,
            step_status={step.step_id: StepStatus.PENDING for step in steps},
        )
        self._store.save(plan_id, context)
        self._event_publisher.publish("task.plan_started", context)
        return self._run(context)

    def resume(self, plan_id: str, *, consent_granted: bool | None = None) -> TaskContext:
        context = self._store.load(plan_id)
        if context is None or context.is_terminal():
            raise A2PlanValidationError(f"plan {plan_id!r} cannot be resumed")
        if context.status is PlanStatus.PAUSED and context.paused_reason == "waiting_consent":
            if consent_granted is True and context.paused_step_id is not None:
                context.step_status[context.paused_step_id] = StepStatus.READY
                context.paused_reason = None
                context.paused_step_id = None
            elif consent_granted is False and context.paused_step_id is not None:
                context.step_status[context.paused_step_id] = StepStatus.CANCELLED
                context.mark_processed(context.paused_step_id)
                context.status = PlanStatus.CANCELLED
                self._store.save(plan_id, context)
                self._event_publisher.publish("task.plan_cancelled", context, current_step=context.paused_step_id)
                return context
        self._store.save(plan_id, context)
        self._event_publisher.publish("task.plan_resumed", context)
        return self._run(context)

    def cancel(self, plan_id: str) -> None:
        context = self._store.load(plan_id)
        if context is None:
            raise A2PlanValidationError(f"plan {plan_id!r} not found")
        context.status = PlanStatus.CANCELLED
        for step_id, status in list(context.step_status.items()):
            if status not in FINAL_STEP_STATUSES:
                context.step_status[step_id] = StepStatus.CANCELLED
                context.mark_processed(step_id)
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
            self._store.save(context.plan_id, context)
            return context

        fallback_chain = tuple(context.context_vars.get("fallback_chain", []) or ())
        if fallback_chain and "route_mode" not in context.context_vars:
            context.context_vars["route_mode"] = fallback_chain[0]
            context.context_vars["fallback_index"] = 0

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
                self._store.save(context.plan_id, context)
                return self._run(context)
        step_events = self._collect_step_events(context)
        plan_events = self._collect_plan_events(context)
        if context.status is PlanStatus.PAUSED and context.paused_reason == "waiting_consent" and context.paused_step_id:
            context.context_vars.setdefault("requires_consent", True)
        if context.status is PlanStatus.PAUSED and context.paused_reason == "waiting_consent":
            step_id = context.paused_step_id
            if step_id is not None:
                consent_request = self._build_consent_request(context, context.steps[step_id])
                context.context_vars["consent_request"] = dataclasses.asdict(consent_request)
                self._store.save(context.plan_id, context)
                self._event_publisher.publish("task.consent_request", context, current_step=step_id)
                if self._consent_adapter is not None:
                    context.context_vars["consent_requested"] = self._consent_adapter.request(consent_request)
                elif self._consent_callback is not None:
                    context.context_vars["consent_requested"] = self._consent_callback(context.plan_id, context.steps[step_id])
        # 状态是唯一真值源：先落盘，再发通知；避免下游收到事件后快照仍是旧值。
        self._store.save(context.plan_id, context)
        for event_name, step_id in step_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        for event_name, step_id in plan_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        return context

    def _build_consent_request(self, context: TaskContext, step: PlanStep) -> ConsentRequest:
        return ConsentRequest(
            plan_id=context.plan_id,
            step_id=step.step_id,
            skill_id=step.skill_id,
            operation="execute_step",
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
        )


def _step_to_dict(step: PlanStep) -> dict[str, Any]:
    payload = dataclasses.asdict(step)
    payload["depends_on"] = list(step.depends_on)
    return payload


def _step_from_dict(payload: dict[str, Any]) -> PlanStep:
    payload["depends_on"] = tuple(payload.get("depends_on", []) or ())
    if "condition_expr" in payload and "condition_key" not in payload:
        payload["condition_key"] = payload.pop("condition_expr")
    payload.pop("timeout_s", None)
    return PlanStep(**payload)
