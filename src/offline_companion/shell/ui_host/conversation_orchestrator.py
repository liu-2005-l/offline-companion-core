"""conversation_orchestrator：单轮对话编排。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

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
from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.runtime.storage_index.engine import append_message, recent_messages
from offline_companion.shared.errors import CloudConnectorError, ReformatError
from offline_companion.shared.types import CloudCompletionRequest, TurnResult


@dataclass
class ConversationOrchestrator:
    """摘要：编排单轮用户输入到助手回复。"""

    session_core: PersonaSessionCore
    backend: object
    conn: sqlite3.Connection
    session_id: str
    triggers: TriggerRegistry
    history_limit: int = 30
    max_tokens: int = 256
    emotion_classifier: EmotionClassifier | None = None

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

    def run_cloud_turn(
        self,
        user_text: str,
        *,
        purpose: str,
        memory_on: bool,
        cloud_post,
    ) -> TurnResult:
        safety = classify_user_text(user_text)
        if safety.tier != SafetyTier.OK:
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

        emotion_context = self._classify_emotion(user_text)
        emotion_meta = emotion_context.raw if emotion_context is not None else {}
        emotion_label = emotion_context.emotion if emotion_context is not None else None
        append_message(
            self.conn,
            self.session_id,
            "user",
            user_text,
            meta={"channel": "cloud", "emotion": emotion_meta},
            emotion=emotion_label,
        )

        cloud_raw: str | None = None
        try:
            response = cloud_post(CloudCompletionRequest(user_message=user_text, purpose=purpose))
            cloud_raw = response.text
            reply = reformat_cloud_reply(
                cloud_raw,
                self.session_core.persona,
                emotion_context=emotion_context,
            )
            append_message(
                self.conn,
                self.session_id,
                "assistant",
                reply,
                meta={"channel": "cloud", "reformatted": True, "emotion": emotion_meta},
                emotion=emotion_label,
            )
            return TurnResult(reply=reply, memory_on=memory_on, cloud_used=True, cloud_degraded=False)
        except (ReformatError, CloudConnectorError, Exception):
            reply = self._local_fallback_reply(user_text, memory_on=memory_on)
            append_message(
                self.conn,
                self.session_id,
                "assistant",
                reply,
                meta={"channel": "cloud_degraded", "had_cloud_raw": bool(cloud_raw), "emotion": emotion_meta},
                emotion=emotion_label,
            )
            return TurnResult(reply=reply, memory_on=memory_on, cloud_used=True, cloud_degraded=True)

    def run_turn(self, user_text: str, *, memory_on: bool) -> TurnResult:
        safety = classify_user_text(user_text)
        if safety.tier != SafetyTier.OK:
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
            return TurnResult(
                reply=clarification_prompt,
                memory_on=memory_on,
                memory_saved=tuple(memory_saved),
                memory_skipped_trigger=memory_skipped,
                memory_only=True,
            )

        if clarification_prompt is not None:
            append_message(self.conn, self.session_id, "assistant", clarification_prompt, meta={"memory": "clarify"})
            return TurnResult(
                reply=clarification_prompt,
                memory_on=memory_on,
                memory_saved=tuple(memory_saved),
                memory_skipped_trigger=memory_skipped,
                memory_only=True,
            )

        emotion_context = self._classify_emotion(chat_text)
        emotion_meta = emotion_context.raw if emotion_context is not None else {}
        emotion_label = emotion_context.emotion if emotion_context is not None else None
        append_message(
            self.conn,
            self.session_id,
            "user",
            chat_text,
            meta={"emotion": emotion_meta},
            emotion=emotion_label,
        )
        history = recent_messages(self.conn, self.session_id, limit=self.history_limit)
        history_for_model = history[:-1] if history and history[-1].role == "user" else history

        assembled = self.session_core.assemble_reply(
            self.backend,
            self.conn,
            user_message=chat_text,
            history=history_for_model,
            memory_enabled=memory_on,
            max_tokens=self.max_tokens,
            emotion_context=emotion_context,
        )
        final_reply = reformat_local_reply(
            assembled.reply,
            emotion_context=emotion_context,
        )
        append_message(
            self.conn,
            self.session_id,
            "assistant",
            final_reply,
            meta={"emotion": emotion_meta, "reformatted": True},
            emotion=emotion_label,
        )

        explanation = (
            get_memory_explanation(assembled.memory_recalls)
            if memory_on and assembled.memory_recalls
            else None
        )
        return TurnResult(
            reply=final_reply,
            memory_on=memory_on,
            memory_saved=tuple(memory_saved),
            memory_skipped_trigger=memory_skipped,
            memory_recalls=tuple(assembled.memory_recalls),
            memory_explanation=explanation,
        )
