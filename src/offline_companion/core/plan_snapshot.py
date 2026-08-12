"""plan_snapshot：计划上下文与步骤定义的快照序列化工具。"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from offline_companion.core.subagent_types import SubagentRole


def serialize(context: Any) -> dict[str, Any]:
    """摘要：将 PlanContext/TaskContext 序列化为可持久化快照。"""
    return {
        "snapshot_version": context.snapshot_version,
        "plan_id": context.plan_id,
        "status": context.status.value,
        "steps": {sid: step_to_dict(step) for sid, step in context.steps.items()},
        "step_status": {sid: status.value for sid, status in context.step_status.items()},
        "step_results": dict(context.step_results),
        "step_errors": dict(context.step_errors),
        "step_attempts": dict(context.step_attempts),
        "processed_steps": list(context.processed_steps),
        "published_step_events": list(context.published_step_events),
        "trace_id": context.trace_id,
        "context_vars": dict(context.context_vars),
        "error": context.error,
        "paused_reason": context.paused_reason,
        "paused_step_id": context.paused_step_id,
        "started_at": context.started_at,
        "updated_at": context.updated_at,
        "completed_at": context.completed_at,
        "step_started_at": dict(context.step_started_at),
        "step_completed_at": dict(context.step_completed_at),
        "step_consent_requests": dict(context.step_consent_requests),
        "step_route_decisions": dict(context.step_route_decisions),
        "progress": context.progress,
    }


def deserialize(payload: Mapping[str, Any], *, context_cls: type[Any] | None = None) -> Any:
    """摘要：从快照字典恢复 TaskContext；兼容旧 snapshot_version=1。"""
    from offline_companion.core.plan_orchestrator import PlanStatus, StepStatus, TaskContext

    resolved_context_cls = context_cls or TaskContext
    snapshot_version = int(payload.get("snapshot_version", 1))
    steps = {
        str(sid): step_from_dict(dict(raw_step))
        for sid, raw_step in dict(payload.get("steps", {})).items()
    }
    step_status = {
        str(sid): StepStatus(str(raw_status))
        for sid, raw_status in dict(payload.get("step_status", {})).items()
    }
    processed_steps = list(payload.get("processed_steps", payload.get("completed_steps", [])))
    return resolved_context_cls(
        plan_id=str(payload["plan_id"]),
        snapshot_version=max(2, snapshot_version),
        status=PlanStatus(str(payload.get("status", PlanStatus.PENDING.value))),
        steps=steps,
        step_status=step_status,
        step_results=dict(payload.get("step_results", {})),
        step_errors=dict(payload.get("step_errors", {})),
        step_attempts={str(key): int(value) for key, value in dict(payload.get("step_attempts", {})).items()},
        processed_steps=[str(item) for item in processed_steps],
        published_step_events=[str(item) for item in payload.get("published_step_events", [])],
        trace_id=str(payload.get("trace_id") or uuid4()),
        context_vars=dict(payload.get("context_vars", {})),
        error=payload.get("error"),
        paused_reason=payload.get("paused_reason"),
        paused_step_id=payload.get("paused_step_id"),
        started_at=optional_float(payload.get("started_at")),
        updated_at=optional_float(payload.get("updated_at")),
        completed_at=optional_float(payload.get("completed_at")),
        step_started_at=float_dict(payload.get("step_started_at")),
        step_completed_at=float_dict(payload.get("step_completed_at")),
        step_consent_requests=dict_of_dict(payload.get("step_consent_requests")),
        step_route_decisions=dict_of_dict(payload.get("step_route_decisions")),
    )


def step_to_dict(step: Any) -> dict[str, Any]:
    """摘要：将 PlanStep 转换为 JSON 友好的字典。"""
    payload = dataclasses.asdict(step)
    payload["depends_on"] = list(step.depends_on)
    payload["files"] = list(step.files)
    return payload


def step_from_dict(payload: dict[str, Any]) -> Any:
    """摘要：从快照字典恢复 PlanStep，并兼容旧字段名。"""
    from offline_companion.core.plan_orchestrator import PlanStep

    payload["depends_on"] = tuple(payload.get("depends_on", []) or ())
    payload["files"] = tuple(str(path) for path in payload.get("files", ()) or ())
    payload["subagent_type"] = normalize_subagent_role(payload.get("subagent_type"))
    if "condition_expr" in payload and "condition_key" not in payload:
        payload["condition_key"] = payload.pop("condition_expr")
    payload.pop("timeout_s", None)
    return PlanStep(**payload)


def normalize_raw_dependencies(raw: Mapping[str, Any], idx: int) -> tuple[str, ...]:
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


def safe_non_negative_int(value: Any) -> int:
    """摘要：将外部输入安全转换为非负整数。"""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_subagent_role(value: Any) -> SubagentRole | None:
    """摘要：归一化计划步骤中的子 Agent 角色字段。"""
    if value is None:
        return None
    text = str(value).strip()
    if text in {"implementer", "reviewer"}:
        return text  # type: ignore[return-value]
    return None


def optional_float(value: Any) -> float | None:
    """摘要：将快照中的可选数值字段转为 float。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def float_dict(value: Any) -> dict[str, float]:
    """摘要：将快照中的时间戳字典转为 `dict[str, float]`。"""
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, float] = {}
    for key, item in value.items():
        parsed = optional_float(item)
        if parsed is not None:
            out[str(key)] = parsed
    return out


def dict_of_dict(value: Any) -> dict[str, dict[str, Any]]:
    """摘要：将快照中的嵌套字典安全转为结构化映射。"""
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            out[str(key)] = dict(item)
    return out
