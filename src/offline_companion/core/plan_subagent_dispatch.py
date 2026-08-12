"""plan_subagent_dispatch：计划步骤到子 Agent 的调度适配。"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from offline_companion.core.subagent_scheduler import SubagentScheduler
from offline_companion.core.subagent_types import SubagentResult
from offline_companion.shared.errors import A2PlanExecutionError

if TYPE_CHECKING:
    from offline_companion.core.plan_orchestrator import PlanStep, TaskContext


class PlanSubagentDispatch:
    """摘要：封装子 Agent spawn → run → result_payload 构造链路。"""

    def __init__(self, scheduler: SubagentScheduler | None = None) -> None:
        """摘要：初始化计划子 Agent 调度器。

        参数：
            scheduler: 可选子 Agent 调度器；为空时不可 dispatch。
        """
        self._scheduler = scheduler

    @property
    def is_available(self) -> bool:
        """摘要：返回是否已注入可用 SubagentScheduler。"""
        return self._scheduler is not None

    def dispatch(
        self,
        context: TaskContext,
        step: PlanStep,
        *,
        parent_session_id: str,
        privacy_mode: str = "local_only",
    ) -> dict[str, Any]:
        """摘要：调度子 Agent 执行 step，返回 result_payload 字典。

        参数：
            context: 当前计划上下文。
            step: 需要执行的计划步骤。
            parent_session_id: 父会话 ID，用于审计与隔离关联。
            privacy_mode: 子 Agent 继承的隐私模式。

        返回值：
            包含 SubagentResult 字段、``subagent_role`` 与 ``subagent_id`` 的字典。

        Raises:
            A2PlanExecutionError: 未注入 scheduler 或步骤缺少 subagent_type。
        """
        if self._scheduler is None:
            raise A2PlanExecutionError("subagent_scheduler is required")
        if step.subagent_type is None:
            raise A2PlanExecutionError("step.subagent_type is required")
        ctx = self._scheduler.spawn(
            parent_session_id=parent_session_id,
            role=step.subagent_type,
            task_description=step.description or step.title,
            allowed_files=list(step.files),
            privacy_mode=privacy_mode,
            plan_id=context.plan_id,
            step_id=step.step_id,
        )
        result = self._scheduler.run(ctx)
        return self.build_result_payload(result, step)

    @staticmethod
    def build_result_payload(result: SubagentResult, step: PlanStep) -> dict[str, Any]:
        """摘要：构造子 Agent 步骤结果，补充角色字段。"""
        payload = dataclasses.asdict(result)
        payload["subagent_role"] = step.subagent_type
        return payload

    @staticmethod
    def handle_subagent_error(context: TaskContext, step: PlanStep, exc: Exception) -> None:
        """摘要：记录子 Agent 调度异常到步骤错误表。"""
        context.step_errors[step.step_id] = str(exc)
        context.touch()
