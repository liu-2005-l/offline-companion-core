"""idle_think_coordinator：A 层 IdleThink 信号协调器。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any
from uuid import uuid4

from offline_companion.core.attention_awareness import AttentionContext
from offline_companion.core.goal_manager.manager import GoalManager, ReminderDecision
from offline_companion.core.plan_orchestrator import (
    PlanContext,
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
    TaskContext,
)
from offline_companion.core.state_manager import StateManager
from offline_companion.shared.types import ReminderCandidate

logger = logging.getLogger(__name__)


class IdleThinkCoordinator:
    """摘要：连接空闲信号、目标提醒评估与系统状态快照。"""

    def __init__(
        self,
        *,
        goal_manager: GoalManager,
        state_manager: StateManager,
        attention_context_provider: Callable[[], AttentionContext] | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        plan_orchestrator: PlanOrchestrator | None = None,
        memory_maintenance: Callable[[float], list[str]] | None = None,
        max_steps_per_idle: int = 10,
    ) -> None:
        """摘要：初始化 IdleThink 协调器。

        参数:
            goal_manager: B 层目标提醒决策入口，内部已包含 AttentionGuard。
            state_manager: 系统状态写入入口。
            attention_context_provider: A 层上下文提供器；缺省时使用空闲上下文。
            settings_provider: A 层设置提供器，用于填充 focus mode 等上下文。
            plan_orchestrator: 可选计划编排器；存在候选时只创建计划，不执行。
            max_steps_per_idle: 单次空闲周期最多推进的步骤数，防止后台长时间占用。
        """
        self._goal_manager = goal_manager
        self._state_manager = state_manager
        self._attention_context_provider = attention_context_provider or (lambda: AttentionContext())
        self._settings_provider = settings_provider or dict
        self._plan_orchestrator = plan_orchestrator
        self._memory_maintenance = memory_maintenance
        self._max_steps_per_idle = max(1, int(max_steps_per_idle))
        self._current_plan_id: str | None = None
        self._interrupted = False
        self._lock = threading.Lock()

    def on_idle(self) -> None:
        """摘要：处理一次空闲信号，写入评估快照但不执行计划。"""
        logger.info("IdleThinkCoordinator.on_idle triggered")
        try:
            if self._memory_maintenance is not None:
                self._memory_maintenance(300.0)
            if self._resume_paused_plan_if_any():
                return
            context = self._build_attention_context()
            decision = self._goal_manager.evaluate_reminders(context)
            idle_plan = self._maybe_create_idle_plan(decision.candidates_to_show)
            self._state_manager.set_system_state(
                "idle_think_result",
                self._decision_to_snapshot(decision, idle_plan=idle_plan),
                actor="idle_think",
            )
            plan_id = idle_plan.get("plan_id") if idle_plan else None
            if plan_id:
                self._execute_plan_steps(str(plan_id))
        except Exception:
            logger.exception("IdleThinkCoordinator.on_idle failed")
        finally:
            self._state_manager.set_system_state("idle_think_requested", False, actor="idle_think")

    def _build_attention_context(self) -> AttentionContext:
        """摘要：由 A 层 settings/state 填充 AttentionContext。"""
        context = self._attention_context_provider()
        settings = self._settings_provider()
        timestamp = time.time()
        context.is_idle = True
        context.last_idle_at = timestamp
        context.is_focus_mode = bool(settings.get("focus_mode_enabled", context.is_focus_mode))
        status = self._state_manager.get_system_state("idle_think_status")
        if isinstance(status, dict) and status.get("timestamp") is not None:
            try:
                context.last_global_reminder_at = float(status["timestamp"])
            except (TypeError, ValueError):
                context.last_global_reminder_at = None
        return context

    def on_user_input(self) -> None:
        """摘要：用户输入时设置协作式中断标志。"""
        with self._lock:
            self._interrupted = True
        logger.info("IdleThink interrupted by user input")

    def close(self) -> None:
        """摘要：请求中断当前 IdleThink 工作，供生命周期卸载使用。"""
        self.on_user_input()

    def _resume_paused_plan_if_any(self) -> bool:
        """摘要：优先恢复上次被用户输入中断的 idle 计划。"""
        status = self._state_manager.get_system_state("idle_think_status")
        if not isinstance(status, dict) or status.get("status") != "paused":
            return False
        plan_id = str(status.get("plan_id") or "")
        if not plan_id or self._plan_orchestrator is None:
            return False
        logger.info("IdleThink resuming paused plan %s", plan_id)
        self._execute_plan_steps(plan_id)
        return True

    def _maybe_create_idle_plan(self, candidates: list[ReminderCandidate]) -> dict[str, Any] | None:
        """摘要：对最高优先级可展示候选创建待执行计划。"""
        if self._plan_orchestrator is None or not candidates:
            return None
        top_candidate = candidates[0]
        goal_title = top_candidate.description.strip() or top_candidate.goal_id
        try:
            steps = self._plan_orchestrator.decide(goal_title)
            if not steps:
                return None
            plan_id = f"idle_{int(time.time())}_{uuid4().hex[:8]}"
            context = self._plan_orchestrator.create_plan(plan_id, steps)
            logger.info("IdleThink generated plan %s with %d steps", context.plan_id, len(steps))
            return self._plan_to_snapshot(context, goal_title=goal_title, steps=steps)
        except Exception:
            logger.exception("IdleThink plan generation failed")
            return None

    def _execute_plan_steps(self, plan_id: str) -> None:
        """摘要：逐步推进 idle 计划；每步之间响应用户输入中断。"""
        if self._plan_orchestrator is None:
            return
        with self._lock:
            self._current_plan_id = plan_id
            self._interrupted = False
        completed = False
        paused = False
        last_context: PlanContext | None = None
        for _ in range(self._max_steps_per_idle):
            if self._is_interrupted():
                paused = True
                break
            context = self._plan_orchestrator.load_context(plan_id)
            if context is None:
                self._write_idle_status(plan_id, "missing")
                return
            if context.is_terminal():
                completed = context.status is PlanStatus.DONE
                last_context = context
                break
            if context.status is PlanStatus.PAUSED and context.paused_reason not in {None, "user_input"}:
                last_context = context
                break
            before_processed = set(context.processed_steps)
            try:
                next_context = self._plan_orchestrator.execute_next(context)
            except Exception:
                logger.exception("IdleThink execute_next failed")
                self._write_idle_status(plan_id, "failed", reason="execute_error")
                return
            last_context = next_context
            self._write_progress_for_new_steps(before_processed, next_context)
            if self._is_interrupted():
                paused = True
                break
            if next_context.is_terminal():
                completed = next_context.status is PlanStatus.DONE
                break
            if next_context.status is PlanStatus.PAUSED:
                break
            if set(next_context.processed_steps) == before_processed:
                break

        if paused:
            self._pause_idle_plan(plan_id)
            return
        if last_context is not None and last_context.is_terminal():
            self._write_idle_status(plan_id, "completed" if completed else last_context.status.value)
            return
        self._write_idle_status(plan_id, "paused", reason="step_budget")

    def _pause_idle_plan(self, plan_id: str) -> None:
        """摘要：将当前 idle 计划标记为用户输入暂停。"""
        if self._plan_orchestrator is not None:
            self._plan_orchestrator.pause(plan_id, reason="user_input")
        self._write_idle_status(plan_id, "paused", reason="user_input")

    def _write_progress_for_new_steps(self, before_processed: set[str], context: PlanContext) -> None:
        """摘要：为本轮新增完成步骤写入进度快照。"""
        for step_id in context.processed_steps:
            if step_id in before_processed:
                continue
            step = context.steps.get(step_id)
            result = None if step is None else context.get_step_result(step_id)
            self._state_manager.set_system_state(
                "idle_think_progress",
                {
                    "plan_id": context.plan_id,
                    "step_id": step_id,
                    "title": "" if step is None else step.title,
                    "result": self._json_safe_value(result),
                    "timestamp": time.time(),
                },
                actor="idle_think",
            )

    def _write_idle_status(self, plan_id: str, status: str, *, reason: str | None = None) -> None:
        """摘要：写入 IdleThink 后台推进状态。"""
        payload: dict[str, Any] = {
            "plan_id": plan_id,
            "status": status,
            "timestamp": time.time(),
        }
        if reason is not None:
            payload["reason"] = reason
        self._state_manager.set_system_state("idle_think_status", payload, actor="idle_think")

    def _is_interrupted(self) -> bool:
        """摘要：读取协作式中断标志。"""
        with self._lock:
            return self._interrupted

    def _plan_to_snapshot(
        self,
        context: TaskContext,
        *,
        goal_title: str,
        steps: list[PlanStep],
    ) -> dict[str, Any]:
        """摘要：将待执行 idle 计划转换为快照字段。"""
        return {
            "plan_id": context.plan_id,
            "goal_title": goal_title,
            "status": context.status.value,
            "step_count": len(steps),
            "steps": [
                {
                    "step_id": step.step_id,
                    "title": step.title,
                    "description": step.description,
                    "expected_output": step.expected_output,
                    "verification": step.verification,
                    "completion_criteria": step.completion_criteria,
                    "stage": step.stage,
                    "estimated_minutes": step.estimated_minutes,
                }
                for step in steps
            ],
        }

    def _decision_to_snapshot(
        self,
        decision: ReminderDecision,
        *,
        idle_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """摘要：将提醒决策转换为可持久化系统状态。"""
        return {
            "timestamp": time.time(),
            "total_candidates": len(decision.candidates_to_show) + len(decision.candidates_silent),
            "show_candidates": len(decision.candidates_to_show),
            "silent_candidates": len(decision.candidates_silent),
            "candidates_to_show": [self._to_plain_dict(candidate) for candidate in decision.candidates_to_show],
            "candidates_silent": [self._to_plain_dict(candidate) for candidate in decision.candidates_silent],
            "context": self._to_plain_dict(decision.context),
            "idle_plan": idle_plan,
            "executed": False,
        }

    def _to_plain_dict(self, value: Any) -> dict[str, Any]:
        """摘要：将 dataclass 或普通对象转换为 JSON 友好的字典。"""
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "__dict__"):
            return {
                key: item
                for key, item in vars(value).items()
                if not key.startswith("_") and isinstance(item, (str, int, float, bool, list, dict, type(None)))
            }
        return {"repr": str(value)}

    def _json_safe_value(self, value: Any) -> Any:
        """摘要：将步骤结果降级为可写入 StateManager 的 JSON 值。"""
        if isinstance(value, (str, int, float, bool, list, dict, type(None))):
            return value
        return str(value)
