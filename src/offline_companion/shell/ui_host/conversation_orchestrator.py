"""conversation_orchestrator：单轮对话编排（A2 职责；由 A1 CLI 调用）。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from offline_companion.core.memory_lifecycle.explanation import get_memory_explanation
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.triggers import (
    TRIGGER_ON_EXPLICIT_SAVE,
    TriggerRegistry,
    is_enabled,
    maybe_summarize_to_memory,
)
from offline_companion.core.local_reformatter.rule_reformatter import (
    LOCAL_FALLBACK_PREFIX,
    reformat_cloud_reply,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.runtime.storage_index.engine import append_message, recent_messages
from offline_companion.shared.errors import CloudConnectorError, ReformatError
from offline_companion.shared.types import CloudCompletionRequest, TurnResult


@dataclass
class ConversationOrchestrator:
    """摘要：编排单轮用户输入到助手回复（安全 → 记忆写入 → 召回 → 推理）。"""

    session_core: PersonaSessionCore
    backend: object
    conn: sqlite3.Connection
    session_id: str
    triggers: TriggerRegistry
    history_limit: int = 30
    max_tokens: int = 256

    def _local_fallback_reply(self, chat_text: str, *, memory_on: bool) -> str:
        """摘要：B4 不可用或云端失败时，用本地 C1 生成并加固定前缀。"""
        hist = recent_messages(self.conn, self.session_id, limit=self.history_limit)
        assembled = self.session_core.assemble_reply(
            self.backend,
            self.conn,
            user_message=chat_text,
            history=hist,
            memory_enabled=memory_on,
            max_tokens=self.max_tokens,
        )
        return LOCAL_FALLBACK_PREFIX + assembled.reply

    def run_cloud_turn(
        self,
        user_text: str,
        *,
        purpose: str,
        memory_on: bool,
        cloud_post,
    ) -> TurnResult:
        """摘要：经 A3 出站 → B4 润色；失败则硬降级为本地回复。

        参数：
            user_text: 用户问题（将最小上传）。
            purpose: 出站目的说明（写入 Consent）。
            memory_on: 本地降级路径是否启用记忆召回。
            cloud_post: 可调用 ``(CloudCompletionRequest) -> CloudCompletionResponse`` 的 A3 函数。

        返回值：
            ``TurnResult``；``cloud_degraded`` 为真表示未使用云端原文。
        """
        safety = classify_user_text(user_text)
        if safety.tier != SafetyTier.OK:
            assert safety.user_visible_reply
            append_message(
                self.conn,
                self.session_id,
                "user",
                user_text,
                meta={"safety": safety.tier.value},
            )
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

        append_message(self.conn, self.session_id, "user", user_text, meta={"channel": "cloud"})
        cloud_raw: str | None = None
        try:
            resp = cloud_post(
                CloudCompletionRequest(user_message=user_text, purpose=purpose),
            )
            cloud_raw = resp.text
            reply = reformat_cloud_reply(cloud_raw, self.session_core.persona)
            append_message(
                self.conn,
                self.session_id,
                "assistant",
                reply,
                meta={"channel": "cloud", "reformatted": True},
            )
            return TurnResult(
                reply=reply,
                memory_on=memory_on,
                cloud_used=True,
                cloud_degraded=False,
            )
        except (ReformatError, CloudConnectorError, Exception):
            # 硬降级：不向用户展示未润色云端原文
            reply = self._local_fallback_reply(user_text, memory_on=memory_on)
            append_message(
                self.conn,
                self.session_id,
                "assistant",
                reply,
                meta={
                    "channel": "cloud_degraded",
                    "had_cloud_raw": bool(cloud_raw),
                },
            )
            return TurnResult(
                reply=reply,
                memory_on=memory_on,
                cloud_used=True,
                cloud_degraded=True,
            )

    def run_turn(self, user_text: str, *, memory_on: bool) -> TurnResult:
        """摘要：处理一条非斜杠用户消息。

        参数：
            user_text: 原始用户输入。
            memory_on: 是否启用记忆写入与召回。

        返回值：
            ``TurnResult``；安全阻断时 ``blocked_by_safety`` 为真。
        """
        safety = classify_user_text(user_text)
        if safety.tier != SafetyTier.OK:
            assert safety.user_visible_reply
            append_message(
                self.conn,
                self.session_id,
                "user",
                user_text,
                meta={"safety": safety.tier.value},
            )
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

        chat_text, mem_lines = MemoryLifecycleManager.maybe_extract_memory_commands(user_text)
        memory_saved: list[str] = []
        memory_skipped = False

        if memory_on and mem_lines:
            if is_enabled(self.triggers, TRIGGER_ON_EXPLICIT_SAVE):
                for m in mem_lines:
                    MemoryLifecycleManager.add_memory_chunk(
                        self.conn,
                        m,
                        session_id=self.session_id,
                        source="user_hash_command",
                    )
                    memory_saved.append(m)
            else:
                memory_skipped = True

        # 预留：摘要写入（默认关）
        _ = maybe_summarize_to_memory(user_text, self.triggers)

        if not chat_text:
            return TurnResult(
                reply=None,
                memory_on=memory_on,
                memory_saved=tuple(memory_saved),
                memory_skipped_trigger=memory_skipped,
                memory_only=True,
            )

        append_message(self.conn, self.session_id, "user", chat_text, meta={})
        hist = recent_messages(self.conn, self.session_id, limit=self.history_limit)
        hist_for_model = hist[:-1] if hist and hist[-1].role == "user" else hist

        assembled = self.session_core.assemble_reply(
            self.backend,
            self.conn,
            user_message=chat_text,
            history=hist_for_model,
            memory_enabled=memory_on,
            max_tokens=self.max_tokens,
        )
        append_message(self.conn, self.session_id, "assistant", assembled.reply, meta={})

        expl = (
            get_memory_explanation(assembled.memory_recalls)
            if memory_on and assembled.memory_recalls
            else None
        )
        return TurnResult(
            reply=assembled.reply,
            memory_on=memory_on,
            memory_saved=tuple(memory_saved),
            memory_skipped_trigger=memory_skipped,
            memory_recalls=tuple(assembled.memory_recalls),
            memory_explanation=expl,
        )
