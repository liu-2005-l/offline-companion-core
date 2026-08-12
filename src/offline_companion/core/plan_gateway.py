"""plan_gateway：计划执行前置门禁、Consent 与阶段证据处理。"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from offline_companion.core.plan_enums import PlanErrorCode
from offline_companion.shared.errors import A2PlanValidationError
from offline_companion.shared.types import PurposeType

if TYPE_CHECKING:
    from offline_companion.core.plan_orchestrator import ConsentRequest, PlanStep, TaskContext


class PlanGateway:
    """摘要：集中处理计划执行前的硬门禁、Consent 暂停与阶段证据。"""

    def __init__(
        self,
        *,
        hard_gate: object | None = None,
        consent_adapter: object | None = None,
        consent_gateway: object | None = None,
        consent_callback: Any | None = None,
        skill_tracker: object | None = None,
    ) -> None:
        """摘要：初始化计划网关。

        参数：
            hard_gate: Skill 阶段前置门禁。
            consent_adapter: 结构化 Consent 适配器。
            consent_gateway: A3 Consent 状态查询入口。
            consent_callback: 旧版 plan_id/step 回调，迁移期兼容。
            skill_tracker: Skill 阶段执行状态与证据存储。
        """
        self._hard_gate = hard_gate
        self._consent_adapter = consent_adapter
        self._consent_gateway = consent_gateway
        self._consent_callback = consent_callback
        self._skill_tracker = skill_tracker

    def prepare_consent_pause(self, context: TaskContext) -> bool:
        """摘要：为等待 Consent 的暂停计划登记真实请求标识。

        参数：
            context: 当前计划上下文。

        返回值：
            是否写入或刷新了 Consent 上下文；无暂停步骤时返回 ``False``。
        """
        step_id = context.paused_step_id
        if not step_id:
            return False
        context.status = _context_status(context, "paused")
        context.paused_reason = PlanErrorCode.WAITING_CONSENT.value
        consent_payload = context.get_step_consent_request(step_id)
        if consent_payload is None:
            consent_request = self.build_consent_request(context, context.steps[step_id])
            consent_payload = dataclasses.asdict(consent_request)
        route_decision = context.get_step_route_decision(step_id)
        if route_decision is None:
            legacy_route_decision = context.get_context_var("route_decision")
            if isinstance(legacy_route_decision, dict):
                route_decision = dict(legacy_route_decision)
        if route_decision is not None:
            context.set_step_route_decision(step_id, route_decision)
        if not consent_payload.get("request_id"):
            consent_request = self.build_consent_request(context, context.steps[step_id])
            if self._consent_adapter is not None:
                context.context_vars["consent_requested"] = self._consent_adapter.request(consent_request)
                artifact = getattr(self._consent_gateway, "last_artifact", None) or {}
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
        return True

    def apply_consent_decision(self, context: TaskContext, request_id: str) -> TaskContext:
        """摘要：验证 A3 已落定的审批结果，并安全更新暂停计划。"""
        step_id = context.paused_step_id
        if context.paused_reason != PlanErrorCode.WAITING_CONSENT.value or step_id is None:
            raise A2PlanValidationError("plan is not waiting for consent")
        consent_payload = context.get_step_consent_request(step_id) or {}
        if str(consent_payload.get("request_id") or "") != request_id:
            raise A2PlanValidationError("consent request does not match paused plan")
        pending = self._consent_gateway.get_pending(request_id) if self._consent_gateway is not None else None
        if pending is None or not pending.decided:
            raise A2PlanValidationError("consent request has not been decided")
        if pending.allowed:
            context.step_status[step_id] = _step_enum(context, "ready")
            context.paused_reason = None
            context.paused_step_id = None
            context.status = _context_status(context, "running")
            context.context_vars["requires_consent"] = False
            context.touch()
        else:
            context.step_status[step_id] = _step_enum(context, "cancelled")
            context.mark_step_completed(step_id)
            context.mark_processed(step_id)
            context.status = _context_status(context, "cancelled")
            context.mark_terminal()
        return context

    def check_hard_gate(
        self,
        context: TaskContext,
        *,
        skill_name: str | None = None,
        skill_stages: list[str] | tuple[str, ...] | None = None,
    ) -> bool:
        """摘要：在执行下一个 ready step 前检查 Skill 阶段硬门禁。"""
        if self._hard_gate is None:
            return False
        ready_steps = context.get_ready_steps()
        if not ready_steps:
            return False
        step = ready_steps[0]
        if not step.stage:
            return False
        session_id = self.session_id(context)
        resolved_skill_name = self.skill_name(context, skill_name)
        if not resolved_skill_name:
            return False
        stages = self.skill_stages(context, skill_stages)
        gate = self._hard_gate.check(session_id, resolved_skill_name, step.stage, stages)
        if gate.get("allowed") is True:
            return False
        missing = [str(item) for item in gate.get("missing", [])] if isinstance(gate.get("missing"), list) else []
        context.step_status[step.step_id] = _step_enum(context, "blocked")
        context.paused_reason = PlanErrorCode.HARD_GATE_BLOCKED.value
        context.paused_step_id = step.step_id
        context.error = str(gate.get("reason") or PlanErrorCode.HARD_GATE_BLOCKED.value)
        context.context_vars["hard_gate"] = {
            "skill_name": resolved_skill_name,
            "stage": step.stage,
            "missing_stages": missing,
            "reason": context.error,
        }
        context.status = _context_status(context, "paused")
        context.touch()
        return True

    def build_consent_request(self, context: TaskContext, step: PlanStep) -> ConsentRequest:
        """摘要：构造计划步骤执行所需的结构化 Consent 请求。"""
        from offline_companion.core.plan_orchestrator import ConsentRequest

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

    def session_id(self, context: TaskContext) -> str:
        """摘要：返回当前计划的可信 session_id。"""
        return str(context.context_vars.get("session_id") or context.plan_id or "default").strip() or "default"

    def skill_name(self, context: TaskContext, fallback: str | None = None) -> str | None:
        """摘要：返回当前计划的 Skill 名称。"""
        return str(context.context_vars.get("skill_name") or fallback or "").strip() or None

    def skill_stages(
        self,
        context: TaskContext,
        fallback: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        """摘要：返回当前计划声明的 Skill 阶段序列。"""
        raw = context.context_vars.get("skill_stages")
        if isinstance(raw, list):
            return [str(stage) for stage in raw if str(stage).strip()]
        return [str(stage) for stage in (fallback or ()) if str(stage).strip()]

    def start_tracked_stage(self, session_id: str, skill_name: str | None, step: PlanStep) -> None:
        """摘要：执行前记录阶段开始状态。"""
        if self._skill_tracker is None or not skill_name or not step.stage:
            return
        self._skill_tracker.start_stage(session_id, skill_name, step.stage)

    def complete_tracked_stage(
        self,
        session_id: str,
        skill_name: str | None,
        step: PlanStep,
        result: Any,
    ) -> None:
        """摘要：执行成功后保存阶段完成证据。"""
        if self._skill_tracker is None or not skill_name or not step.stage:
            return
        evidence = verify_evidence(step, result)
        self._skill_tracker.complete_stage(session_id, skill_name, step.stage, evidence)

    def fail_tracked_stage(self, session_id: str, skill_name: str | None, step: PlanStep, reason: str) -> None:
        """摘要：执行失败后保存阶段失败原因。"""
        if self._skill_tracker is None or not skill_name or not step.stage:
            return
        self._skill_tracker.fail_stage(session_id, skill_name, step.stage, reason)


def verify_evidence(step: PlanStep, result: Any) -> str:
    """摘要：从步骤结果和计划字段中提取并校验非空阶段证据。"""
    if isinstance(result, Mapping):
        raw = result.get("evidence") or result.get("verification") or result.get("result")
        if raw and str(raw).strip():
            return str(raw)
    fallback = step.verification or step.expected_output
    if fallback and str(fallback).strip():
        return str(fallback)
    raise A2PlanValidationError(PlanErrorCode.EVIDENCE_MISSING.value)


def _step_enum(context: Any, value: str) -> Any:
    """摘要：根据当前 context 中已有 step_status 推断 StepStatus Enum 类型。"""
    sample = next(iter(context.step_status.values()), None)
    if sample is None:
        return value
    enum_type = type(sample)
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return value


def _context_status(context: Any, value: str) -> Any:
    """摘要：用现有 context.status 类型构造同类计划状态。"""
    enum_type = type(context.status)
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return value
