"""plan_orchestrator：A2 任务规划与执行编排。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import sleep, time
from typing import Any, Protocol
from uuid import uuid4

from offline_companion.core import plan_snapshot
from offline_companion.core.plan_dag_engine import PlanDAGEngine
from offline_companion.core.plan_decomposer import PlanDecomposer
from offline_companion.core.plan_enums import PlanErrorCode, PlanEventName
from offline_companion.core.plan_gateway import PlanGateway
from offline_companion.core.plan_subagent_dispatch import PlanSubagentDispatch
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
DEPENDENCY_FAILED_STATUSES = frozenset({StepStatus.FAILED, StepStatus.BLOCKED, StepStatus.CANCELLED})
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
    plan_status: str | None = None
    started_at: float | None = None
    updated_at: float | None = None
    completed_at: float | None = None
    step_started_at: dict[str, float] = field(default_factory=dict)
    step_completed_at: dict[str, float] = field(default_factory=dict)
    step_consent_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    step_route_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    feedback_overrides: dict[str, str] = field(default_factory=dict)
    quality_retry_counts: dict[str, int] = field(default_factory=dict)
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
        """摘要：委托 plan_snapshot 序列化当前计划上下文。"""
        return plan_snapshot.serialize(self)

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> TaskContext:
        """摘要：委托 plan_snapshot 从持久化快照恢复计划上下文。"""
        return plan_snapshot.deserialize(payload, context_cls=cls)

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
        self._dag_engine = PlanDAGEngine()
        self._skill_invoker = self._normalize_skill_invoker(skill_invoker)
        self._fallback_controller = None
        self._routed_invoker = None
        self._gateway = PlanGateway(
            hard_gate=hard_gate,
            consent_adapter=consent_adapter,
            consent_gateway=consent_gateway,
            consent_callback=consent_callback,
            skill_tracker=skill_tracker,
        )
        self.consent_gateway = consent_gateway
        self._decomposer = PlanDecomposer(llm_router=llm_backend, skill_resolver=skill_resolver)
        self._subagent_dispatch = PlanSubagentDispatch(scheduler=subagent_scheduler)
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
        """摘要：委托 PlanDecomposer 将用户目标拆解为可执行计划步骤。

        参数：
            user_input: 用户提交的完整目标文本。

        返回值：
            满足 DAG 依赖关系的 ``PlanStep`` 列表；空输入返回空列表。
        """
        steps = self._decomposer.decide(user_input)
        self._skill_name = self._decomposer.skill_name
        self._skill_stages = list(self._decomposer.skill_stages)
        return steps

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
        self._dag_engine.validate_dag(step_map)
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
        self._dag_engine.validate_dag(step_map)
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
        if context.status is PlanStatus.PAUSED and context.paused_reason == PlanErrorCode.WAITING_CONSENT.value:
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

        context = self._dag_engine.run_until_blocked(context, executor, sleep_fn=sleep)
        if context.status is PlanStatus.FAILED and context.context_vars.get("fallback_chain") and self._fallback_controller is not None:
            failed_step = context.paused_step_id or next((sid for sid, status in context.step_status.items() if status is StepStatus.FAILED), None)
            if self._fallback_controller.advance(context, reason=context.error or "step_failed", step_id=failed_step, error=context.error):
                context.status = PlanStatus.RUNNING
                context.error = None
                context.completed_at = None
                context.touch()
                self._store.save(context.plan_id, context)
                return self._run(context)
        consent_prepared = False
        if self._finalize_plan_status(context) is None and context.status is PlanStatus.FAILED:
            context.status = PlanStatus.RUNNING
            context.completed_at = None
            context.touch()
        step_events = self._collect_step_events(context)
        plan_events = self._collect_plan_events(context)
        if context.status is PlanStatus.PAUSED and context.paused_reason == PlanErrorCode.WAITING_CONSENT.value and context.paused_step_id:
            context.context_vars.setdefault("requires_consent", True)
            context.touch()
        if context.status is PlanStatus.PAUSED and context.paused_reason == PlanErrorCode.WAITING_CONSENT.value:
            consent_prepared = self._gateway.prepare_consent_pause(context)
        # 状态是唯一真值源：先落盘，再发通知；避免下游收到事件后快照仍是旧值。
        self._store.save(context.plan_id, context)
        for event_name, step_id in step_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        for event_name, step_id in plan_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        if consent_prepared:
            self._event_publisher.publish("task.consent_request", context, current_step=context.paused_step_id)
        return context

    def execute_next(
        self,
        context: PlanContext | str,
        *,
        invoke_skill: Callable[[PlanStep, TaskContext], Any] | None = None,
    ) -> PlanContext:
        """摘要：执行至多一个 DAG 步骤，供 SSE 编排器逐步推进计划。"""
        if isinstance(context, str):
            loaded = self.load_context(context)
            if loaded is None:
                raise A2PlanValidationError(f"plan {context!r} not found")
            context = loaded
        if context.plan_status in {"completed", "failed", "blocked"}:
            return context
        if context.status in {PlanStatus.DONE, PlanStatus.CANCELLED}:
            return context
        if context.status is PlanStatus.FAILED and self._finalize_plan_status(context) is not None:
            self._store.save(context.plan_id, context)
            return context
        if context.status is PlanStatus.FAILED:
            context.status = PlanStatus.RUNNING
            context.completed_at = None
            context.touch()
        if context.status is PlanStatus.PAUSED and context.paused_reason == PlanErrorCode.HARD_GATE_BLOCKED.value:
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
        gate_blocked = self._gateway.check_hard_gate(
            context,
            skill_name=self._skill_name,
            skill_stages=self._skill_stages,
        )
        if gate_blocked:
            self._store.save(context.plan_id, context)
            self._event_publisher.publish("task.plan_blocked", context, current_step=context.paused_step_id)
            return context

        previous_statuses = dict(context.step_status)

        def executor(step: PlanStep, context_vars: dict[str, Any]) -> Any:
            session_id = self._gateway.session_id(context)
            skill_name = self._gateway.skill_name(context, self._skill_name)
            self._gateway.start_tracked_stage(session_id, skill_name, step)
            try:
                result = self._execute_step_with_quality_retry(
                    context,
                    step,
                    context_vars,
                    session_id=session_id,
                    skill_name=skill_name,
                )
            except (A2PlanExecutionError, KeyError, RuntimeError, TimeoutError, ConnectionError, ValueError) as exc:
                if step.subagent_type is not None:
                    self._subagent_dispatch.handle_subagent_error(context, step, exc)
                self._gateway.fail_tracked_stage(session_id, skill_name, step, str(exc))
                raise
            self._gateway.complete_tracked_stage(session_id, skill_name, step, result)
            return result

        context = self._dag_engine.run_until_blocked(context, executor, sleep_fn=sleep, max_steps=1)
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
            context = self._dag_engine.run_until_blocked(context, executor, sleep_fn=sleep, max_steps=1)

        for failed_step_id, status in list(context.step_status.items()):
            if status is StepStatus.FAILED:
                self._dag_engine.propagate_failure(context, failed_step_id)
        self._propagate_unblock_events(context, previous_statuses)
        self._finalize_plan_status(context)

        if context.paused_reason == PlanErrorCode.WAITING_CONSENT.value and context.paused_step_id:
            consent_prepared = self._gateway.prepare_consent_pause(context)
        else:
            consent_prepared = False
        step_events = self._collect_step_events(context)
        plan_events = self._collect_plan_events(context)
        self._store.save(context.plan_id, context)
        for event_name, step_id in step_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        for event_name, step_id in plan_events:
            self._event_publisher.publish(event_name, context, current_step=step_id)
        if consent_prepared:
            self._event_publisher.publish("task.consent_request", context, current_step=context.paused_step_id)
        return context

    def apply_consent_decision(self, context: PlanContext, request_id: str) -> PlanContext:
        """摘要：委托 PlanGateway 验证 A3 审批结果并更新计划状态。"""
        context = self._gateway.apply_consent_decision(context, request_id)
        self._store.save(context.plan_id, context)
        return context

    def retry_failed_step(self, plan_id: str, step_id: str, user_feedback: str | None = None) -> TaskContext:
        """摘要：手动重置失败步骤，交由下一次 execute_next 走完整执行与校验链路。

        参数：
            plan_id: 计划 ID。
            step_id: 需要重试的失败步骤 ID。
            user_feedback: 可选用户反馈，会注入下一次执行上下文。

        返回值：
            已更新并持久化的计划上下文。

        Raises:
            A2PlanValidationError: 计划不存在、步骤不存在或步骤不是 failed 状态。
        """
        context = self._store.load(plan_id)
        if context is None:
            raise A2PlanValidationError(f"plan {plan_id!r} not found")
        step = context.steps.get(step_id)
        if step is None:
            raise A2PlanValidationError(f"step {step_id!r} not found")
        if _step_status_value(context.step_status.get(step_id)) != StepStatus.FAILED.value:
            raise A2PlanValidationError(f"step {step_id!r} is not FAILED")

        context.step_status[step_id] = StepStatus.PENDING
        context.step_errors.pop(step_id, None)
        context.step_attempts.pop(step_id, None)
        context.step_results.pop(step.result_key, None)
        context.context_vars.pop(step.result_key, None)
        context.quality_retry_counts.pop(step_id, None)
        context.step_started_at.pop(step_id, None)
        context.step_completed_at.pop(step_id, None)
        context.processed_steps = [item for item in context.processed_steps if item != step_id]
        context.published_step_events = [item for item in context.published_step_events if item != step_id]
        if context.paused_step_id == step_id:
            context.paused_reason = None
            context.paused_step_id = None
        if user_feedback:
            context.feedback_overrides[step_id] = user_feedback
        else:
            context.feedback_overrides.pop(step_id, None)
        context.status = PlanStatus.RUNNING
        context.error = None
        context.completed_at = None
        context.plan_status = None
        context.touch()
        self._store.save(plan_id, context)
        self._event_publisher.publish("task.step_retry", context, current_step=step_id)
        return context

    def _execute_step_with_quality_retry(
        self,
        context: TaskContext,
        step: PlanStep,
        context_vars: dict[str, Any],
        *,
        session_id: str,
        skill_name: str | None,
    ) -> Any:
        """摘要：执行单步并在后置校验失败时最多带反馈重试一次。"""
        del session_id, skill_name
        result = self._execute_step_raw(context, step, context_vars)
        post_issues = self._gateway.verify_post_execution(step, result) if step.stage else []
        if not post_issues:
            context.feedback_overrides.pop(step.step_id, None)
            return result
        if context.quality_retry_counts.get(step.step_id, 0) >= 1:
            context.paused_reason = PlanErrorCode.POST_VERIFICATION_FAILED.value
            context.paused_step_id = step.step_id
            context.touch()
            raise A2PlanValidationError("; ".join(post_issues))

        context.quality_retry_counts[step.step_id] = context.quality_retry_counts.get(step.step_id, 0) + 1
        context.feedback_overrides[step.step_id] = self._gateway.build_retry_feedback(step, post_issues)
        retry_events = context.context_vars.setdefault("quality_retry_events", [])
        if isinstance(retry_events, list):
            retry_events.append(
                {
                    "event": PlanEventName.STEP_RETRY.value,
                    "step_id": step.step_id,
                    "issues": list(post_issues),
                }
            )
        context.touch()
        self._store.save(context.plan_id, context)

        retry_result = self._execute_step_raw(context, step, context_vars)
        retry_issues = self._gateway.verify_post_execution(step, retry_result) if step.stage else []
        if retry_issues:
            context.paused_reason = PlanErrorCode.POST_VERIFICATION_FAILED.value
            context.paused_step_id = step.step_id
            context.touch()
            raise A2PlanValidationError("; ".join(retry_issues))
        context.feedback_overrides.pop(step.step_id, None)
        context.touch()
        return retry_result

    def _execute_step_raw(self, context: TaskContext, step: PlanStep, context_vars: dict[str, Any]) -> Any:
        """摘要：执行一次计划步骤，不做 DAG 推进或质量重试。"""
        feedback = context.feedback_overrides.get(step.step_id)
        if step.subagent_type is not None and self._subagent_dispatch.is_available:
            return self._subagent_dispatch.dispatch(
                context,
                step,
                parent_session_id=self._gateway.session_id(context),
                privacy_mode=str(context_vars.get("privacy_mode") or self._privacy_mode or "local_only"),
            )
        if self._routed_invoker is not None:
            if feedback:
                context.context_vars["_quality_retry_feedback"] = feedback
            try:
                return self._routed_invoker.invoke_step(step, context)
            finally:
                context.context_vars.pop("_quality_retry_feedback", None)
        if self._skill_invoker is None:
            raise A2PlanExecutionError("skill_invoker is required")
        payload = dict(step.payload)
        if context_vars.get("route_mode") is not None:
            payload["_route_mode"] = context_vars.get("route_mode")
        if context_vars.get("fallback_chain") is not None:
            payload["_fallback_chain"] = list(context_vars.get("fallback_chain") or [])
        if context_vars.get("fallback_index") is not None:
            payload["_fallback_index"] = int(context_vars.get("fallback_index") or 0)
        if feedback:
            payload["_quality_retry_feedback"] = feedback
        return self._skill_invoker.invoke(step.skill_id, payload, step.idempotency_key)

    def _propagate_unblock_events(self, context: TaskContext, previous_statuses: Mapping[str, Any]) -> None:
        """摘要：对本轮新完成步骤执行下游解除阻断，并暂存待发布事件。"""
        unblocked_events = context.context_vars.setdefault("_step_unblocked_events", [])
        for step_id, status in list(context.step_status.items()):
            if _step_status_value(status) != StepStatus.DONE.value:
                continue
            if _step_status_value(previous_statuses.get(step_id)) == StepStatus.DONE.value:
                continue
            unblocked = self._dag_engine.propagate_unblock(context, step_id)
            if isinstance(unblocked_events, list):
                unblocked_events.extend(unblocked)

    def _finalize_plan_status(self, context: TaskContext) -> str | None:
        """摘要：当计划所有步骤都不可继续调度时缓存最终 plan_status。"""
        if context.plan_status in {"completed", "failed", "blocked"}:
            return None
        if context.status is PlanStatus.PAUSED and context.paused_reason in {
            PlanErrorCode.WAITING_CONSENT.value,
            PlanErrorCode.HARD_GATE_BLOCKED.value,
        }:
            return None
        statuses = {_step_status_value(status) for status in context.step_status.values()}
        if statuses & {StepStatus.PENDING.value, StepStatus.READY.value, StepStatus.RUNNING.value}:
            return None
        status = self._gateway.evaluate_plan_status(context)
        if status not in {"completed", "failed", "blocked"}:
            return None
        if status == "blocked" and not statuses & {StepStatus.FAILED.value, StepStatus.CANCELLED.value}:
            return None
        context.plan_status = status
        if status == "completed":
            context.status = PlanStatus.DONE
        else:
            context.status = PlanStatus.FAILED
        context.mark_terminal()
        return status

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

    def _collect_step_events(self, context: TaskContext) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        unblocked_events = context.context_vars.pop("_step_unblocked_events", [])
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
            elif status is StepStatus.BLOCKED:
                events.append(("task.step_blocked", step_id))
            else:
                continue
            context.published_step_events.append(step_id)
            published.add(step_id)
        if isinstance(unblocked_events, list):
            for step_id in unblocked_events:
                events.append(("task.step_unblocked", str(step_id)))
        return events

    def _collect_plan_events(self, context: TaskContext) -> list[tuple[str, str | None]]:
        if context.plan_status == "completed":
            return [("task.plan_completed", None)]
        if context.plan_status == "blocked":
            return [("task.plan_blocked", context.paused_step_id)]
        if context.plan_status == "failed":
            return [("task.plan_failed", None)]
        if context.status is PlanStatus.PAUSED and context.paused_reason == PlanErrorCode.WAITING_CONSENT.value:
            return [("task.plan_paused", context.paused_step_id)]
        if context.status is PlanStatus.DONE:
            return [("task.plan_completed", None)]
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
            subagent_type=plan_snapshot.normalize_subagent_role(item.get("subagent_type")),
        )


def _step_status_value(status: Any) -> str:
    """摘要：兼容 Enum 或字符串形式的步骤状态。"""
    return str(getattr(status, "value", status))
