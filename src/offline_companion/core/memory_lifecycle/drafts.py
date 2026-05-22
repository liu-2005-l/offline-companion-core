"""drafts：记忆摘要草稿（规则提取；确认后才写入 memory_chunks）。"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from offline_companion.runtime.storage_index.engine import recent_messages
from offline_companion.shared.types import MessageRow

from . import fts_ops

# 参与摘要的最近消息条数上限（约 3～5 轮）
_SUMMARY_MESSAGE_LIMIT = 10
_KEY_LINE_MAX = 120


@dataclass(frozen=True)
class MemoryDraftRow:
    """摘要：一条待确认的记忆草稿。"""

    id: int
    session_id: str
    body: str
    status: str
    created_at: float


def _extract_entities(text: str) -> list[str]:
    """摘要：从文本中提取偏好/实体短语（规则，非模型）。"""
    found: list[str] = []
    patterns = [
        r"#remember\s+(.+)",
        r"请记住[：:]?\s*(.+)",
        r"我(?:叫|是)([^\s，。！？]{1,12})",
        r"我(?:喜欢|讨厌|不爱吃|忌口)([^\s，。！？]{1,16})",
        r"(?:I like|I hate|I am)\s+([A-Za-z0-9\s]{2,40})",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            snippet = m.group(1).strip()
            if snippet and snippet not in found:
                found.append(snippet[:80])
    return found[:8]


def build_extractive_summary(messages: list[MessageRow]) -> str:
    """摘要：用关键实体 + 最近对话句组成结构化草稿（不调 C1）。

    参数：
        messages: 按时间正序的消息列表。

    返回值：
        供用户审阅的草稿正文（中文说明 + 要点）。
    """
    if not messages:
        return "【摘要草稿】暂无对话内容可总结。"

    blob = "\n".join(f"{m.role}: {m.content}" for m in messages)
    entities = _extract_entities(blob)
    recent = messages[-_SUMMARY_MESSAGE_LIMIT:]
    lines: list[str] = []
    for m in recent:
        role = "用户" if m.role == "user" else "助手"
        content = m.content.strip().replace("\n", " ")
        if len(content) > _KEY_LINE_MAX:
            content = content[:_KEY_LINE_MAX] + "…"
        lines.append(f"  - {role}：{content}")

    parts = [
        "【摘要草稿】以下内容尚未写入正式记忆；请使用 /memory confirm <id> 保存，或 /memory discard <id> 丢弃。",
        "",
    ]
    if entities:
        parts.append("要点（规则提取）：")
        for e in entities:
            parts.append(f"  · {e}")
        parts.append("")
    parts.append("近期对话摘录：")
    parts.extend(lines)
    return "\n".join(parts)


def create_draft_from_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    message_limit: int = _SUMMARY_MESSAGE_LIMIT,
) -> MemoryDraftRow:
    """摘要：根据会话最近消息生成并保存草稿。

    参数：
        conn: 主库连接。
        session_id: 会话 ID。
        message_limit: 读取最近消息条数上限。

    返回值：
        新建的 ``MemoryDraftRow``。
    """
    hist = recent_messages(conn, session_id, limit=message_limit)
    body = build_extractive_summary(hist)
    meta = {
        "generator": "extractive_rules",
        "message_count": len(hist),
        "entities": _extract_entities("\n".join(m.content for m in hist)),
    }
    now = time.time()
    cur = conn.execute(
        "INSERT INTO memory_drafts(session_id, body, meta_json, created_at, status) "
        "VALUES(?,?,?,?,?);",
        (session_id, body, json.dumps(meta, ensure_ascii=False), now, "pending"),
    )
    rid = cur.lastrowid
    assert rid is not None
    return MemoryDraftRow(id=int(rid), session_id=session_id, body=body, status="pending", created_at=now)


def list_pending_drafts(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    limit: int = 20,
) -> list[MemoryDraftRow]:
    """摘要：列出某会话下待确认的草稿。"""
    rows = conn.execute(
        "SELECT id, session_id, body, status, created_at FROM memory_drafts "
        "WHERE session_id = ? AND status = 'pending' ORDER BY id DESC LIMIT ?;",
        (session_id, limit),
    ).fetchall()
    return [
        MemoryDraftRow(
            id=int(r["id"]),
            session_id=str(r["session_id"]),
            body=str(r["body"]),
            status=str(r["status"]),
            created_at=float(r["created_at"]),
        )
        for r in rows
    ]


def get_draft(conn: sqlite3.Connection, draft_id: int) -> MemoryDraftRow | None:
    """摘要：按 ID 读取草稿（任意状态）。"""
    r = conn.execute(
        "SELECT id, session_id, body, status, created_at FROM memory_drafts WHERE id = ?;",
        (draft_id,),
    ).fetchone()
    if not r:
        return None
    return MemoryDraftRow(
        id=int(r["id"]),
        session_id=str(r["session_id"]),
        body=str(r["body"]),
        status=str(r["status"]),
        created_at=float(r["created_at"]),
    )


def confirm_draft(conn: sqlite3.Connection, draft_id: int) -> int | None:
    """摘要：将草稿确认为正式记忆（写入 memory_chunks）。

    返回值：
        新建 ``memory_chunks.id``；失败返回 None。
    """
    draft = get_draft(conn, draft_id)
    if not draft or draft.status != "pending":
        return None
    # 仅存要点行作为记忆正文，避免把整段 UI 说明写入 FTS
    meta = conn.execute(
        "SELECT meta_json FROM memory_drafts WHERE id = ?;", (draft_id,)
    ).fetchone()
    entities: list[str] = []
    if meta and meta["meta_json"]:
        try:
            entities = list(json.loads(meta["meta_json"]).get("entities") or [])
        except json.JSONDecodeError:
            entities = []
    if entities:
        body = "；".join(entities)
    else:
        body = draft.body.split("近期对话摘录：", 1)[0].strip() or draft.body[:500]
    chunk_id = fts_ops.add_memory_chunk(
        conn, body, session_id=draft.session_id, source="draft_confirm"
    )
    conn.execute(
        "UPDATE memory_drafts SET status = 'confirmed' WHERE id = ?;", (draft_id,)
    )
    return chunk_id


def discard_draft(conn: sqlite3.Connection, draft_id: int) -> bool:
    """摘要：丢弃草稿（不写入 memory_chunks）。"""
    draft = get_draft(conn, draft_id)
    if not draft or draft.status != "pending":
        return False
    conn.execute("UPDATE memory_drafts SET status = 'discarded' WHERE id = ?;", (draft_id,))
    return True


def count_memory_chunks(conn: sqlite3.Connection) -> int:
    """摘要：统计正式记忆条数（测试隔离用）。"""
    row = conn.execute("SELECT COUNT(*) AS c FROM memory_chunks;").fetchone()
    return int(row["c"]) if row else 0
