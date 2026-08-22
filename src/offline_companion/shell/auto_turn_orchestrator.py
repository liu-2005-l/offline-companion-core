"""auto_turn_orchestrator：Auto 模式单轮计划编排入口。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from offline_companion.core.decomposition_result import NotDecomposableResult
from offline_companion.core.event_stream import EventStream
from offline_companion.core.plan_enums import PlanErrorCode, PlanEventName
from offline_companion.core.plan_evidence_schema import STAGE_EVIDENCE_SCHEMA
from offline_companion.core.plan_orchestrator import (
    PlanContext,
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
    StepStatus,
)
from offline_companion.shared.errors import A2PlanValidationError
from offline_companion.shared.messages import BaseMessage
from offline_companion.shell.plan_auto_bridge import PlanAutoBridge
from offline_companion.shell.plan_final_reply import FinalReplySummarizer, build_final_reply

PlanStepInvoker = Callable[[PlanStep, PlanContext], Any]


@dataclass
class ConversationPlanInvoker:
    """摘要：把 Auto 计划中的通用对话步骤交给当前本地会话模型。"""

    conversation_orchestrator: Any

    def invoke(self, skill_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        """摘要：执行通用对话步骤；非 chat 步骤由外层组合调用器处理。"""
        del idempotency_key
        if skill_id != "chat":
            raise KeyError(f"unsupported auto conversation skill: {skill_id}")
        goal = str(payload.get("query") or "").strip()
        description = str(payload.get("description") or goal).strip()
        completed = payload.get("_step_results") or {}
        stage = str(payload.get("stage") or "").strip()
        required_fields = STAGE_EVIDENCE_SCHEMA.get(stage, [])
        stage_requirement = ""
        if required_fields:
            stage_requirement = (
                f"\n当前阶段：{stage}\n"
                f"验收证据字段：{', '.join(required_fields)}\n"
                "请在结果中逐项明确给出这些证据。"
            )
        quality_retry_feedback = str(payload.get("_quality_retry_feedback") or "").strip()
        retry_requirement = f"\n质量校验反馈：\n{quality_retry_feedback}" if quality_retry_feedback else ""
        prompt = (
            f"用户目标：{goal}\n当前步骤：{description}\n"
            f"已完成步骤：{json.dumps(completed, ensure_ascii=False)}\n"
            "请只输出当前步骤的结果，并保持简洁。"
            f"{stage_requirement}{retry_requirement}"
        )
        assembled = self.conversation_orchestrator.session_core.assemble_reply(
            self.conversation_orchestrator.backend,
            self.conversation_orchestrator.conn,
            user_message=prompt,
            history=[],
            memory_enabled=False,
            max_tokens=self.conversation_orchestrator.max_tokens,
            capability_profile=self.conversation_orchestrator._local_capability_profile(),
            audit_arithmetic=False,
        )
        return {"result": assembled.reply, "route_mode": "local"}

    def summarize_final_reply(self, prompt: str) -> str:
        """摘要：使用当前本地会话模型生成计划终态正文。

        参数：
            prompt: 已包含步骤终态的总结提示。

        返回值：
            本地模型生成的最终回复。
        """
        if getattr(self.conversation_orchestrator.backend, "label", None) == "local-unavailable":
            raise RuntimeError("local model unavailable for final reply summary")
        assembled = self.conversation_orchestrator.session_core.assemble_reply(
            self.conversation_orchestrator.backend,
            self.conversation_orchestrator.conn,
            user_message=prompt,
            history=[],
            memory_enabled=False,
            max_tokens=self.conversation_orchestrator.max_tokens,
            capability_profile=self.conversation_orchestrator._local_capability_profile(),
            audit_arithmetic=False,
        )
        return assembled.reply


@dataclass
class AutoTurnOrchestrator:
    """摘要：编排 Auto 单轮的规则拆解、逐步骤路由和同步执行。"""

    plan_orchestrator: PlanOrchestrator
    auto_bridge: PlanAutoBridge
    invoke_skill: PlanStepInvoker
    event_stream: EventStream | None = None
    final_reply_summarizer: FinalReplySummarizer | None = None

    def execute_turn(
        self,
        message: BaseMessage,
        user_input: str,
        *,
        plan_id: str | None = None,
    ) -> PlanContext | NotDecomposableResult:
        """摘要：执行完整 Auto turn 并返回可持久化计划上下文。"""
        resolved_plan_id = plan_id or f"auto_{uuid4().hex}"
        steps = self.plan_orchestrator.decide(user_input)
        if isinstance(steps, NotDecomposableResult):
            return steps
        if not steps:
            raise ValueError("Auto 模式无法拆解空输入")
        context = self.plan_orchestrator.create_context(resolved_plan_id)
        context.context_vars["original_input"] = user_input
        context.context_vars["session_id"] = message.session_id or resolved_plan_id
        context.steps = {step.step_id: step for step in steps}
        context.step_status = {
            step.step_id: self.plan_orchestrator._default_step_status(step.step_id)
            for step in steps
        }
        routed = self.auto_bridge.prepare(message, plan_id=resolved_plan_id, context=context)
        return self.auto_bridge.execute_routed(
            plan_id=resolved_plan_id,
            invoke_skill=self.invoke_skill,
            context=routed,
        )

    def execute_turn_stream(
        self,
        message: BaseMessage,
        user_input: str,
        *,
        plan_id: str | None = None,
        resume: bool = False,
        consent_request_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """摘要：逐步骤执行 Auto turn，并生成可直接编码为 SSE 的事件。"""
        if resume:
            if not plan_id:
                yield {"type": PlanEventName.ERROR.value, "error": "resume requires plan_id"}
                return
            context = self.plan_orchestrator.load_context(plan_id)
            if context is None:
                yield {"type": PlanEventName.ERROR.value, "error": f"plan {plan_id} not found"}
                return
            if context.paused_reason == PlanErrorCode.WAITING_CONSENT.value:
                if not consent_request_id:
                    yield {"type": PlanEventName.ERROR.value, "error": "resume requires consent_request_id"}
                    return
                try:
                    context = self.plan_orchestrator.apply_consent_decision(context, consent_request_id)
                except A2PlanValidationError as exc:
                    yield {"type": PlanEventName.ERROR.value, "error": str(exc), "plan_id": context.plan_id}
                    return
                if context.status is PlanStatus.CANCELLED:
                    yield {
                        "type": PlanEventName.PLAN_CANCELLED.value,
                        "plan_id": context.plan_id,
                        "reply": build_final_reply(context, summarizer=self.final_reply_summarizer),
                        "done": True,
                    }
                    return
        else:
            resolved_plan_id = plan_id or f"auto_{uuid4().hex}"
            steps = self.plan_orchestrator.decide(user_input)
            if isinstance(steps, NotDecomposableResult):
                yield {
                    "type": PlanEventName.NOT_DECOMPOSABLE.value,
                    "status": steps.status,
                    "reason": steps.reason,
                    "done": True,
                }
                return
            if not steps:
                yield {"type": PlanEventName.ERROR.value, "error": "Auto 模式无法拆解空输入"}
                return
            context = self.plan_orchestrator.create_context(resolved_plan_id)
            context.context_vars["original_input"] = user_input
            context.context_vars["session_id"] = message.session_id or resolved_plan_id
            context.steps = {step.step_id: step for step in steps}
            context.step_status = {
                step.step_id: self.plan_orchestrator._default_step_status(step.step_id)
                for step in steps
            }
            context = self.auto_bridge.prepare(message, plan_id=resolved_plan_id, context=context)

        yield {
            "type": PlanEventName.PLAN_START.value,
            "plan_id": context.plan_id,
            "resume": resume,
            "steps": [self._step_event_payload(context, step) for step in context.steps.values()],
        }

        while not context.is_terminal():
            ready_steps = context.get_ready_steps()
            if not ready_steps:
                context = self.plan_orchestrator.execute_next(context, invoke_skill=self.invoke_skill)
                if context.paused_reason == PlanErrorCode.HARD_GATE_BLOCKED.value:
                    yield self._blocked_event(context)
                    return
                if context.paused_reason == PlanErrorCode.WAITING_CONSENT.value:
                    yield self._consent_event(context)
                    return
                if not context.is_terminal():
                    break
                continue
            next_step = ready_steps[0]
            if self.event_stream is not None:
                self.event_stream.append(
                    "plan/step_started",
                    {
                        "plan_id": context.plan_id,
                        "step_id": next_step.step_id,
                        "step_title": next_step.title,
                        "trace_id": context.trace_id,
                    },
                )
            yield {"type": PlanEventName.STEP_START.value, **self._step_event_payload(context, next_step)}
            previous_processed = set(context.processed_steps)
            context = self.plan_orchestrator.execute_next(context, invoke_skill=self.invoke_skill)
            if context.paused_reason == PlanErrorCode.HARD_GATE_BLOCKED.value:
                yield self._blocked_event(context)
                return
            if context.paused_reason == PlanErrorCode.WAITING_CONSENT.value:
                yield self._consent_event(context)
                return
            newly_processed = [
                step_id
                for step_id in context.processed_steps
                if step_id not in previous_processed
            ]
            for step_id in newly_processed:
                status = context.step_status.get(step_id)
                if status is StepStatus.DONE:
                    completed_step = context.steps[step_id]
                    yield {
                        "type": PlanEventName.STEP_COMPLETE.value,
                        "step_id": step_id,
                        "title": completed_step.title,
                        "stage": completed_step.stage,
                        "status": "completed",
                        "evidence": self._step_evidence(completed_step, context.get_step_result(step_id)),
                        "result": context.get_step_result(step_id),
                    }
                elif status is StepStatus.DEGRADED:
                    completed_step = context.steps[step_id]
                    yield {
                        "type": PlanEventName.STEP_COMPLETE.value,
                        "step_id": step_id,
                        "title": completed_step.title,
                        "stage": completed_step.stage,
                        "status": "degraded",
                        "evidence": self._step_evidence(completed_step, context.get_step_result(step_id)),
                        "degraded": True,
                        "result": context.get_step_result(step_id),
                    }
                elif status is StepStatus.SKIPPED:
                    yield {"type": PlanEventName.STEP_SKIPPED.value, "step_id": step_id}
                elif status is StepStatus.FAILED:
                    failed_step = context.steps[step_id]
                    yield {
                        "type": PlanEventName.STEP_FAILED.value,
                        "step_id": step_id,
                        "title": failed_step.title,
                        "stage": failed_step.stage,
                        "error": context.step_errors.get(step_id),
                        "message": context.step_errors.get(step_id),
                    }

        if context.status is PlanStatus.DONE:
            final_reply = build_final_reply(context, summarizer=self.final_reply_summarizer)
            yield {
                "type": PlanEventName.PLAN_COMPLETE.value,
                **auto_turn_to_payload(context, final_reply=final_reply),
                "done": True,
            }
        elif context.status is PlanStatus.FAILED:
            yield {
                "type": PlanEventName.PLAN_FAILED.value,
                "error": context.error,
                "plan_id": context.plan_id,
                "reply": build_final_reply(context, summarizer=self.final_reply_summarizer),
                "done": True,
            }
        elif context.status is PlanStatus.CANCELLED:
            yield {
                "type": PlanEventName.PLAN_CANCELLED.value,
                "plan_id": context.plan_id,
                "reply": build_final_reply(context, summarizer=self.final_reply_summarizer),
                "done": True,
            }
        else:
            yield {
                "type": PlanEventName.ERROR.value,
                "error": context.paused_reason or "plan stopped before terminal state",
                "plan_id": context.plan_id,
                "done": True,
            }

    @staticmethod
    def _step_event_payload(context: PlanContext, step: PlanStep) -> dict[str, Any]:
        """摘要：构造步骤事件共用字段。"""
        return {
            "step_id": step.step_id,
            "title": step.title,
            "description": step.description or step.payload.get("description", ""),
            "expected_output": step.expected_output,
            "verification": step.verification,
            "completion_criteria": step.completion_criteria,
            "stage": step.stage,
            "estimated_minutes": step.estimated_minutes,
            "files": list(step.files),
            "route_mode": (context.get_step_route_decision(step.step_id) or {}).get("mode"),
        }

    @staticmethod
    def _step_evidence(step: PlanStep, result: Any) -> str:
        """摘要：提取 SSE 可展示的步骤验证证据。"""
        if isinstance(result, dict):
            raw = result.get("evidence") or result.get("verification") or result.get("result")
            if raw:
                return str(raw)
        return step.verification or step.expected_output or ""

    @staticmethod
    def _blocked_event(context: PlanContext) -> dict[str, Any]:
        """摘要：构造硬门禁阻断事件。"""
        payload = context.context_vars.get("hard_gate", {})
        missing = [str(item) for item in payload.get("missing_stages") or []]
        stage = str(payload.get("stage") or "")
        message = (
            f"阶段「{stage}」的前置条件未满足。请先完成：{', '.join(missing)}"
            if missing
            else f"阶段「{stage}」未通过硬门禁。"
        )
        return {
            "type": PlanEventName.PLAN_BLOCKED.value,
            "plan_id": context.plan_id,
            "blocked_step_id": context.paused_step_id,
            "missing_stages": missing,
            "message": message,
            "done": True,
        }

    @staticmethod
    def _consent_event(context: PlanContext) -> dict[str, Any]:
        """摘要：构造等待 A3 决策的暂停事件。"""
        step_id = context.paused_step_id
        consent_payload = context.get_step_consent_request(step_id or "") or {}
        return {
            "type": PlanEventName.CONSENT_REQUIRED.value,
            "step_id": step_id,
            "consent_request_id": consent_payload.get("request_id"),
            "plan_id": context.plan_id,
            "consent_payload": consent_payload,
        }


def auto_turn_to_payload(context: PlanContext, *, final_reply: str | None = None) -> dict[str, Any]:
    """摘要：把 Auto 计划上下文转换为现有聊天 UI 可消费的最终 payload。"""
    reply = final_reply if final_reply is not None else build_final_reply(context)
    return {
        "reply": reply,
        "blocked": False,
        "memory_saved": [],
        "memory_recall_count": 0,
        "route_mode": "auto",
        "routing_reason": context.state.get("auto_route_reason"),
        "plan_id": context.plan_id,
        "plan_status": context.status.value,
        "requires_consent": context.paused_reason == PlanErrorCode.WAITING_CONSENT.value,
        "steps": [
            {
                "step_id": step_id,
                "description": step.payload.get("description", ""),
                "status": context.step_status[step_id].value,
                "route": (context.get_step_route_decision(step_id) or {}).get("mode"),
                "result": context.get_step_result(step_id),
            }
            for step_id, step in context.steps.items()
        ],
    }
