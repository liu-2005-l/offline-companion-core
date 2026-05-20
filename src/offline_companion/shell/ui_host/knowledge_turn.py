"""knowledge_turn：知识检索单轮编排（A1/A2；本地 FTS，默认不过 B4）。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from offline_companion.core.knowledge_rag.config import KnowledgeConfig
from offline_companion.core.knowledge_rag.format import format_knowledge_reference_block, format_knowledge_snippets
from offline_companion.core.knowledge_rag.search import KnowledgeSearchHit, search_knowledge
from offline_companion.core.local_reformatter.rule_reformatter import reformat_cloud_reply
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.runtime.storage_index.engine import append_message, recent_messages
from offline_companion.shared.errors import ReformatError
from offline_companion.shared.types import Persona


@dataclass(frozen=True)
class KnowledgeTurnResult:
    """摘要：知识检索命令结果。"""

    snippet_display: str
    hits: tuple[KnowledgeSearchHit, ...]
    reply: str | None = None
    blocked_by_safety: bool = False
    safety_reply: str | None = None
    answer_after_search: bool = False


def run_knowledge_search(
    *,
    query: str,
    config: KnowledgeConfig,
    knowledge_conn: sqlite3.Connection,
    companion_conn: sqlite3.Connection,
    session_id: str,
    persona: Persona,
    session_core: PersonaSessionCore,
    backend: object,
    memory_on: bool,
) -> KnowledgeTurnResult:
    """摘要：执行 ``/search-knowledge`` 流程（B3 → 检索 → 展示 / 可选 C1+B4）。

    参数：
        query: 用户检索词。
        config: 知识配置。
        knowledge_conn: ``knowledge.db`` 连接。
        companion_conn: 主会话库（落库与可选生成）。
        session_id: 会话 ID。
        persona: 人设。
        session_core: B1 装配。
        backend: C1 后端。
        memory_on: ``answer_after_search`` 时是否同时启用个人记忆召回。

    返回值：
        ``KnowledgeTurnResult``。
    """
    safety = classify_user_text(query)
    if safety.tier != SafetyTier.OK:
        assert safety.user_visible_reply
        return KnowledgeTurnResult(
            snippet_display="",
            hits=(),
            reply=safety.user_visible_reply,
            blocked_by_safety=True,
            safety_reply=safety.user_visible_reply,
        )

    hits = search_knowledge(
        knowledge_conn,
        query,
        limit=config.top_k,
        session_id=session_id,
    )
    display = format_knowledge_snippets(hits, max_chars=config.max_snippet_chars)

    if not config.answer_after_search:
        return KnowledgeTurnResult(
            snippet_display=display,
            hits=tuple(hits),
            answer_after_search=False,
        )

    ref_block = format_knowledge_reference_block(hits, max_chars=config.max_snippet_chars)
    append_message(companion_conn, session_id, "user", query, meta={"channel": "knowledge_search"})
    hist = recent_messages(companion_conn, session_id, limit=30)
    assembled = session_core.assemble_reply(
        backend,
        companion_conn,
        user_message=query,
        history=hist[:-1] if hist and hist[-1].role == "user" else hist,
        memory_enabled=memory_on,
        max_tokens=256,
        reference_block=ref_block,
    )
    try:
        reply = reformat_cloud_reply(assembled.reply, persona)
    except ReformatError:
        reply = assembled.reply
    append_message(
        companion_conn,
        session_id,
        "assistant",
        reply,
        meta={"channel": "knowledge_answer", "reformatted": True},
    )
    return KnowledgeTurnResult(
        snippet_display=display,
        hits=tuple(hits),
        reply=reply,
        answer_after_search=True,
    )
