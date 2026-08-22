"""plan_final_reply：统一生成手动与 Auto 计划的终态回复。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from offline_companion.core.arithmetic_verifier import audit_arithmetic_reply
from offline_companion.core.plan_orchestrator import PlanStatus, TaskContext

logger = logging.getLogger(__name__)

FinalReplySummarizer = Callable[[str], str]


def build_final_reply(
    context: TaskContext,
    *,
    summarizer: FinalReplySummarizer | None = None,
) -> str | None:
    """摘要：按统一终态语义生成计划正文，阻断态返回空。

    参数：
        context: 已执行或已停止的计划上下文。
        summarizer: 可选的本地模型总结函数。

    返回值：
        终态正文；非终态或可恢复阻断态返回 ``None``。
    """
    status = context.status.value
    completed, total = _completion_counts(context)
    if status == PlanStatus.CANCELLED.value:
        return f"任务已取消，完成 {completed}/{total} 步骤。"
    if context.plan_status == "blocked" or context.paused_reason in {
        "hard_gate_blocked",
        "waiting_consent",
    }:
        return None
    if status not in {PlanStatus.DONE.value, PlanStatus.FAILED.value}:
        return None

    aggregate = aggregate_step_results(context)
    if summarizer is None:
        if status == PlanStatus.DONE.value and aggregate:
            return audit_arithmetic_reply(aggregate, retry_allowed=False).reply
        deterministic = _deterministic_reply(status, completed, total, aggregate)
        return audit_arithmetic_reply(deterministic, retry_allowed=False).reply

    prompt = _summary_prompt(context, status, completed, total)
    retry_allowed = not any(int(count or 0) > 0 for count in context.quality_retry_counts.values())
    try:
        reply = str(summarizer(prompt)).strip()
        if reply:
            return audit_arithmetic_reply(
                reply,
                retry=lambda feedback: summarizer(f"{prompt}\n\n【算术校验反馈】\n{feedback}"),
                retry_allowed=retry_allowed,
            ).reply
    except Exception:
        logger.warning("计划终态总结生成失败，降级为确定性正文", exc_info=True)
    deterministic = _deterministic_reply(status, completed, total, aggregate)
    return audit_arithmetic_reply(deterministic, retry_allowed=False).reply


def aggregate_step_results(context: TaskContext) -> str:
    """摘要：按步骤顺序聚合现有结果，保持 Auto 旧回复语义。"""
    parts: list[str] = []
    for step_id in context.steps:
        result = context.get_step_result(step_id)
        if isinstance(result, dict) and result.get("result") is not None:
            parts.append(str(result["result"]))
        elif result is not None:
            parts.append(str(result))
    return "\n\n".join(part for part in parts if part.strip())


def _completion_counts(context: TaskContext) -> tuple[int, int]:
    completed_statuses = {"done", "degraded", "skipped"}
    completed = sum(
        1
        for status in context.step_status.values()
        if getattr(status, "value", str(status)) in completed_statuses
    )
    return completed, len(context.steps)


def _deterministic_reply(status: str, completed: int, total: int, aggregate: str) -> str:
    label = "任务已完成" if status == PlanStatus.DONE.value else "任务执行失败"
    summary = f"{label}，完成 {completed}/{total} 步骤。"
    return f"{summary}\n\n执行结果：\n{aggregate}" if aggregate else summary


def _summary_prompt(context: TaskContext, status: str, completed: int, total: int) -> str:
    outcomes: list[dict[str, Any]] = []
    for step_id, step in context.steps.items():
        step_status = context.step_status.get(step_id)
        outcomes.append(
            {
                "step_id": step_id,
                "title": step.title,
                "status": getattr(step_status, "value", str(step_status or "unknown")),
                "result": context.get_step_result(step_id),
                "error": context.step_errors.get(step_id),
            }
        )
    manual_plan = context.context_vars.get("manual_plan")
    goal = str(manual_plan.get("goal") or "").strip() if isinstance(manual_plan, dict) else ""
    if not goal:
        goal = str(context.context_vars.get("user_input") or context.context_vars.get("goal") or "").strip()
    return (
        "请根据计划执行结果生成面向用户的最终回复。不要复述内部状态字段，不要声称未发生的操作。\n"
        f"用户目标：{goal or '未提供'}\n"
        f"计划状态：{status}\n完成进度：{completed}/{total}\n"
        f"步骤结果：{json.dumps(outcomes, ensure_ascii=False, default=str)}"
    )
