"""摘要：单轮对话编排，支持模型路由、同意暂停与恢复。"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from offline_companion.core.emotion_analyzer import EmotionClassifier
from offline_companion.core.local_reformatter.rule_reformatter import (
    LOCAL_FALLBACK_PREFIX,
    reformat_cloud_reply,
    reformat_local_reply,
)
from offline_companion.core.memory_lifecycle.explanation import get_memory_explanation
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.memory_store import MemoryStoreController
from offline_companion.core.memory_lifecycle.triggers import (
    TRIGGER_ON_EXPLICIT_SAVE,
    TriggerRegistry,
    is_enabled,
    maybe_summarize_to_memory,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.plan_orchestrator import ConsentRequest
from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.runtime.storage_index.engine import append_message, recent_messages
from offline_companion.shared.errors import CloudConnectorError, ReformatError
from offline_companion.shared.types import (
    CloudCompletionRequest,
    ModelRoutingDecision,
    PrivacyMode,
    PurposeType,
    TurnResult,
)
from offline_companion.shell.model_router import ModelRouter
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway

CloudPost = Callable[[CloudCompletionRequest], Any]


@dataclass(frozen=True)
class _PreparedTurn:
    """摘要：通过安全与记忆预处理、尚未落库的单轮输入。"""

    chat_text: str
    memory_on: bool
    memory_saved: tuple[str, ...]
    memory_skipped: bool


@dataclass(frozen=True)
class _EmotionPayload:
    """摘要：单轮情绪识别结果及其序列化元信息。"""

    context: Any | None
    meta: dict[str, Any]
    label: str | None


@dataclass(frozen=True)
class PendingRoutedTurn:
    """摘要：等待用户同意后恢复执行的单轮上下文。"""

    prepared: _PreparedTurn
    decision: ModelRoutingDecision
    purpose: str


@dataclass
class ConversationOrchestrator:
    """摘要：编排单轮用户输入到本地/云端回复。"""

    session_core: PersonaSessionCore
    backend: object
    conn: sqlite3.Connection
    session_id: str
    triggers: TriggerRegistry
    history_limit: int = 30
    max_tokens: int = 256
    emotion_classifier: EmotionClassifier | None = None
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_ONLY
    model_router: ModelRouter | None = None
    consent_gateway: UIHostConsentGateway | None = None
    cloud_post: CloudPost | None = None
    pending_turns: dict[str, PendingRoutedTurn] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.emotion_classifier is None:
            self.emotion_classifier = EmotionClassifier()

    def _classify_emotion(self, text: str):
        if self.emotion_classifier is None:
            return None
        try:
            return self.emotion_classifier.predict(text)
        except Exception:
            return None

    def _emotion_payload(self, text: str) -> _EmotionPayload:
        context = self._classify_emotion(text)
        meta = context.raw if context is not None else {}
        label = context.emotion if context is not None else None
        return _EmotionPayload(context=context, meta=meta, label=label)

    def _safety_result(self, user_text: str, *, memory_on: bool) -> TurnResult | None:
        safety = classify_user_text(user_text)
        if safety.tier == SafetyTier.OK:
            return None
        assert safety.user_visible_reply
        append_message(self.conn, self.session_id, "user", user_text, meta={"safety": safety.tier.value})
        append_message(
            self.conn,
            self.session_id,
            "assistant",
            safety.user_visible_reply,
            meta={"safety": "fixed_reply"},
        )
        return TurnResult(
            reply=safety.user_visible_reply,
            memory_on=memory_on,
            blocked_by_safety=True,
            safety_tier=safety.tier.value,
        )

    def _prepare_turn(self, user_text: str, *, memory_on: bool) -> tuple[_PreparedTurn | None, TurnResult | None]:
        chat_text, memory_lines = MemoryLifecycleManager.maybe_extract_memory_commands(user_text)
        memory_saved: list[str] = []
        memory_skipped = False

        if memory_on and memory_lines:
            if is_enabled(self.triggers, TRIGGER_ON_EXPLICIT_SAVE):
                for item in memory_lines:
                    MemoryLifecycleManager.add_memory_chunk(
                        self.conn,
                        item,
                        session_id=self.session_id,
                        source="user_hash_command",
                    )
                    memory_saved.append(item)
            else:
                memory_skipped = True

        memory_store = MemoryStoreController()
        memory_store.bind(self.conn, self.session_id)
        clarification_prompt: str | None = None
        if memory_on:
            confirm_text = user_text.strip()
            confirmations = {"对", "是", "是的", "确认", "记住", "记住吧", "好的", "同意"}
            if memory_store.has_pending() and confirm_text in confirmations:
                pending_id = memory_store.pending_ids()[-1]
                store_action = memory_store.confirm_pending(pending_id)
            else:
                store_action = memory_store.handle_input(user_text)
            if store_action.get("action") == "write" and store_action.get("memory_item") is not None:
                item = store_action["memory_item"]
                MemoryLifecycleManager.add_memory_chunk(
                    self.conn,
                    str(item["body"]),
                    session_id=self.session_id,
                    source=str(item["source"]),
                    meta=dict(item["meta_json"]),
                )
                memory_saved.append(str(item["body"]))
            elif store_action.get("action") == "clarify":
                clarification_prompt = str(store_action.get("reply") or "请确认记忆内容。")

        _ = maybe_summarize_to_memory(user_text, self.triggers)

        if not chat_text:
            return None, TurnResult(
                reply=clarification_prompt,
                memory_on=memory_on,
                memory_saved=tuple(memory_saved),
                memory_skipped_trigger=memory_skipped,
                memory_only=True,
            )

        if clarification_prompt is not None:
            append_message(self.conn, self.session_id, "assistant", clarification_prompt, meta={"memory": "clarify"})
            return None, TurnResult(
                reply=clarification_prompt,
                memory_on=memory_on,
                memory_saved=tuple(memory_saved),
                memory_skipped_trigger=memory_skipped,
                memory_only=True,
            )

        return _PreparedTurn(
            chat_text=chat_text,
            memory_on=memory_on,
            memory_saved=tuple(memory_saved),
            memory_skipped=memory_skipped,
        ), None

    def _append_user_message(
        self,
        chat_text: str,
        *,
        emotion: _EmotionPayload,
        channel: str,
        routing: dict[str, Any] | None = None,
    ) -> None:
        meta: dict[str, Any] = {"channel": channel, "emotion": emotion.meta}
        if routing is not None:
            meta["routing"] = routing
        append_message(
            self.conn,
            self.session_id,
            "user",
            chat_text,
            meta=meta,
            emotion=emotion.label,
        )

    def _append_assistant_message(
        self,
        reply: str,
        *,
        emotion: _EmotionPayload,
        channel: str,
        routing: dict[str, Any] | None = None,
        extra_meta: dict[str, Any] | None = None,
    ) -> None:
        meta: dict[str, Any] = {"channel": channel, "emotion": emotion.meta}
        if routing is not None:
            meta["routing"] = routing
        if extra_meta:
            meta.update(extra_meta)
        append_message(
            self.conn,
            self.session_id,
            "assistant",
            reply,
            meta=meta,
            emotion=emotion.label,
        )

    def _routing_meta(self, decision: ModelRoutingDecision, route_mode: str) -> dict[str, Any]:
        return {
            "mode": route_mode,
            "selected_model": decision.selected_model,
            "fallback_model": decision.fallback_model,
            "reason": decision.reason,
            "estimated_input_tokens": decision.estimated_input_tokens,
            "estimated_output_tokens": decision.estimated_output_tokens,
            "estimated_cost": decision.estimated_cost,
        }

    def _turn_result_with_route(
        self,
        *,
        reply: str | None,
        prepared: _PreparedTurn,
        decision: ModelRoutingDecision,
        route_mode: str,
        cloud_used: bool = False,
        cloud_degraded: bool = False,
        memory_recalls: tuple[Any, ...] = (),
        memory_explanation: dict[str, Any] | None = None,
        requires_consent: bool = False,
        consent_request_id: str | None = None,
    ) -> TurnResult:
        return TurnResult(
            reply=reply,
            memory_on=prepared.memory_on,
            memory_saved=prepared.memory_saved,
            memory_skipped_trigger=prepared.memory_skipped,
            memory_recalls=memory_recalls,
            memory_explanation=memory_explanation,
            cloud_used=cloud_used,
            cloud_degraded=cloud_degraded,
            requires_consent=requires_consent,
            consent_request_id=consent_request_id,
            route_mode=route_mode,
            selected_model=decision.selected_model or None,
            fallback_model=decision.fallback_model,
            routing_reason=decision.reason,
            estimated_input_tokens=decision.estimated_input_tokens,
            estimated_output_tokens=decision.estimated_output_tokens,
            estimated_cost=decision.estimated_cost,
        )

    def _execute_local_prepared(
        self,
        prepared: _PreparedTurn,
        *,
        decision: ModelRoutingDecision | None = None,
        route_mode: str = "local",
        user_message_appended: bool = False,
    ) -> TurnResult:
        emotion = self._emotion_payload(prepared.chat_text)
        routing = self._routing_meta(decision, route_mode) if decision is not None else None
        if not user_message_appended:
            self._append_user_message(prepared.chat_text, emotion=emotion, channel=route_mode, routing=routing)
        history = recent_messages(self.conn, self.session_id, limit=self.history_limit)
        history_for_model = history[:-1] if history and history[-1].role == "user" else history
        assembled = self.session_core.assemble_reply(
            self.backend,
            self.conn,
            user_message=prepared.chat_text,
            history=history_for_model,
            memory_enabled=prepared.memory_on,
            max_tokens=self.max_tokens,
            emotion_context=emotion.context,
        )
        final_reply = reformat_local_reply(assembled.reply, emotion_context=emotion.context)
        self._append_assistant_message(
            final_reply,
            emotion=emotion,
            channel=route_mode,
            routing=routing,
            extra_meta={"reformatted": True},
        )
        explanation = (
            get_memory_explanation(assembled.memory_recalls)
            if prepared.memory_on and assembled.memory_recalls
            else None
        )
        if decision is None:
            return TurnResult(
                reply=final_reply,
                memory_on=prepared.memory_on,
                memory_saved=prepared.memory_saved,
                memory_skipped_trigger=prepared.memory_skipped,
                memory_recalls=tuple(assembled.memory_recalls),
                memory_explanation=explanation,
            )
        return self._turn_result_with_route(
            reply=final_reply,
            prepared=prepared,
            decision=decision,
            route_mode=route_mode,
            memory_recalls=tuple(assembled.memory_recalls),
            memory_explanation=explanation,
        )

    def _execute_cloud_once(
        self,
        prepared: _PreparedTurn,
        *,
        purpose: str,
        cloud_post: CloudPost,
        decision: ModelRoutingDecision,
        route_mode: str,
    ) -> TurnResult:
        emotion = self._emotion_payload(prepared.chat_text)
        routing = self._routing_meta(decision, route_mode)
        self._append_user_message(prepared.chat_text, emotion=emotion, channel=route_mode, routing=routing)
        response = cloud_post(CloudCompletionRequest(user_message=prepared.chat_text, purpose=purpose))
        cloud_raw = str(response.text)
        reply = reformat_cloud_reply(
            cloud_raw,
            self.session_core.persona,
            emotion_context=emotion.context,
        )
        self._append_assistant_message(
            reply,
            emotion=emotion,
            channel=route_mode,
            routing=routing,
            extra_meta={"reformatted": True},
        )
        return self._turn_result_with_route(
            reply=reply,
            prepared=prepared,
            decision=decision,
            route_mode=route_mode,
            cloud_used=True,
        )

    def _execute_cloud_with_fallback(
        self,
        prepared: _PreparedTurn,
        *,
        purpose: str,
        cloud_post: CloudPost,
        decision: ModelRoutingDecision,
    ) -> TurnResult:
        route_mode = self._route_mode_for_model(decision.selected_model)
        if route_mode != "cloud":
            return self._execute_local_prepared(prepared, decision=decision, route_mode=route_mode or "local")
        try:
            return self._execute_cloud_once(
                prepared,
                purpose=purpose,
                cloud_post=cloud_post,
                decision=decision,
                route_mode="cloud",
            )
        except (ReformatError, CloudConnectorError, Exception):
            if not decision.fallback_model:
                raise
            reply = self._local_fallback_reply(prepared.chat_text, memory_on=prepared.memory_on)
            emotion = self._emotion_payload(prepared.chat_text)
            routing = self._routing_meta(decision, "cloud")
            routing["executed_fallback_model"] = decision.fallback_model
            self._append_assistant_message(
                reply,
                emotion=emotion,
                channel="cloud_degraded",
                routing=routing,
                extra_meta={"had_cloud_raw": False},
            )
            return self._turn_result_with_route(
                reply=reply,
                prepared=prepared,
                decision=decision,
                route_mode="cloud",
                cloud_used=True,
                cloud_degraded=True,
            )

    def _route_mode_for_model(self, model_name: str | None) -> str | None:
        if self.model_router is None or not model_name:
            return None
        return self.model_router.model_type(model_name)

    def _local_fallback_reply(self, chat_text: str, *, memory_on: bool) -> str:
        emotion_context = self._classify_emotion(chat_text)
        history = recent_messages(self.conn, self.session_id, limit=self.history_limit)
        assembled = self.session_core.assemble_reply(
            self.backend,
            self.conn,
            user_message=chat_text,
            history=history,
            memory_enabled=memory_on,
            max_tokens=self.max_tokens,
            emotion_context=emotion_context,
        )
        final_reply = reformat_local_reply(assembled.reply, emotion_context=emotion_context)
        return LOCAL_FALLBACK_PREFIX + final_reply

    def _build_routing_consent_request(
        self,
        prepared: _PreparedTurn,
        decision: ModelRoutingDecision,
        *,
        purpose: str,
    ) -> ConsentRequest:
        return ConsentRequest(
            plan_id=self.session_id,
            step_id="turn",
            skill_id="skill_cloud_inference",
            operation="route_cloud_turn",
            risk_level="high",
            impact_scope="single_turn",
            source="conversation_orchestrator",
            metadata={
                "purpose_type": PurposeType.CLOUD_ROUTING.value,
                "purpose": purpose,
                "selected_model": decision.selected_model,
                "fallback_model": decision.fallback_model,
                "routing_reason": decision.reason,
                "estimated_input_tokens": decision.estimated_input_tokens,
                "estimated_output_tokens": decision.estimated_output_tokens,
                "estimated_cost": decision.estimated_cost,
                "message_preview": prepared.chat_text[:120],
            },
        )

    def _submit_routing_consent(
        self,
        prepared: _PreparedTurn,
        decision: ModelRoutingDecision,
        *,
        purpose: str,
    ) -> TurnResult:
        if self.consent_gateway is None:
            return self._execute_cloud_with_fallback(
                prepared,
                purpose=purpose,
                cloud_post=self.cloud_post,
                decision=decision,
            )
        request = self._build_routing_consent_request(prepared, decision, purpose=purpose)
        allowed = self.consent_gateway.submit(request)
        artifact = self.consent_gateway.last_artifact or {}
        request_id = str(artifact.get("request_id") or "")
        if request_id:
            self.pending_turns[request_id] = PendingRoutedTurn(
                prepared=prepared,
                decision=decision,
                purpose=purpose,
            )
        pending = self.consent_gateway.get_pending(request_id or None)
        if pending is not None and pending.decided:
            self.pending_turns.pop(pending.request_id, None)
            if pending.allowed:
                return self._execute_cloud_with_fallback(
                    prepared,
                    purpose=purpose,
                    cloud_post=self.cloud_post,
                    decision=decision,
                )
            return self._turn_result_with_route(
                reply="已取消本轮云端请求。",
                prepared=prepared,
                decision=decision,
                route_mode="cloud",
            )
        if allowed and request_id:
            self.pending_turns.pop(request_id, None)
            return self._execute_cloud_with_fallback(
                prepared,
                purpose=purpose,
                cloud_post=self.cloud_post,
                decision=decision,
            )
        return self._turn_result_with_route(
            reply=None,
            prepared=prepared,
            decision=decision,
            route_mode="cloud",
            requires_consent=True,
            consent_request_id=request_id or None,
        )

    def run_cloud_turn(
        self,
        user_text: str,
        *,
        purpose: str,
        memory_on: bool,
        cloud_post,
    ) -> TurnResult:
        safety_result = self._safety_result(user_text, memory_on=memory_on)
        if safety_result is not None:
            return safety_result
        prepared, early_result = self._prepare_turn(user_text, memory_on=memory_on)
        if early_result is not None:
            return early_result
        assert prepared is not None
        decision = ModelRoutingDecision(
            selected_model="cloud",
            fallback_model="local",
            requires_consent=False,
            reason="explicit_cloud_turn",
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            estimated_cost=0.0,
        )
        try:
            return self._execute_cloud_once(
                prepared,
                purpose=purpose,
                cloud_post=cloud_post,
                decision=decision,
                route_mode="cloud",
            )
        except (ReformatError, CloudConnectorError, Exception):
            reply = self._local_fallback_reply(prepared.chat_text, memory_on=prepared.memory_on)
            emotion = self._emotion_payload(prepared.chat_text)
            self._append_assistant_message(
                reply,
                emotion=emotion,
                channel="cloud_degraded",
                routing=self._routing_meta(decision, "cloud"),
                extra_meta={"had_cloud_raw": False},
            )
            return self._turn_result_with_route(
                reply=reply,
                prepared=prepared,
                decision=decision,
                route_mode="cloud",
                cloud_used=True,
                cloud_degraded=True,
            )

    def run_turn(self, user_text: str, *, memory_on: bool) -> TurnResult:
        safety_result = self._safety_result(user_text, memory_on=memory_on)
        if safety_result is not None:
            return safety_result
        prepared, early_result = self._prepare_turn(user_text, memory_on=memory_on)
        if early_result is not None:
            return early_result
        assert prepared is not None
        if self.model_router is None or self.cloud_post is None:
            return self._execute_local_prepared(prepared)
        decision = self.model_router.route(prepared.chat_text, privacy_mode=self.privacy_mode)
        if not decision.selected_model:
            return self._turn_result_with_route(
                reply="当前没有满足约束的可用模型。",
                prepared=prepared,
                decision=decision,
                route_mode="none",
            )
        if decision.requires_consent:
            return self._submit_routing_consent(
                prepared,
                decision,
                purpose="Cloud routing for current turn",
            )
        return self._execute_cloud_with_fallback(
            prepared,
            purpose="Cloud routing for current turn",
            cloud_post=self.cloud_post,
            decision=decision,
        )

    def resume_pending_turn(self, request_id: str, *, allowed: bool) -> TurnResult:
        """摘要：恢复一条等待同意的单轮请求。"""
        pending_turn = self.pending_turns.pop(request_id, None)
        if pending_turn is None:
            raise KeyError(f"unknown pending turn request_id: {request_id}")
        if self.consent_gateway is not None:
            pending = self.consent_gateway.get_pending(request_id)
            if pending is not None and not pending.decided:
                self.consent_gateway.decide(request_id, allowed)
        if not allowed:
            return self._turn_result_with_route(
                reply="已取消本轮云端请求。",
                prepared=pending_turn.prepared,
                decision=pending_turn.decision,
                route_mode="cloud",
            )
        if self.cloud_post is None:
            raise RuntimeError("cloud_post is required to resume routed cloud turn")
        return self._execute_cloud_with_fallback(
            pending_turn.prepared,
            purpose=pending_turn.purpose,
            cloud_post=self.cloud_post,
            decision=pending_turn.decision,
        )
