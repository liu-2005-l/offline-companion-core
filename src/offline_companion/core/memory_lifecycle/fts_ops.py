"""fts_ops：记忆块与 FTS 检索（B2 子模块；仅 SQLite）。"""

from __future__ import annotations

import json
import sqlite3
import time

from offline_companion.shared.errors import B2MemoryWriteError
from offline_companion.shared.types import MemoryHit

from .embedding import maybe_write_embedding


def _fts_escape_query(q: str) -> str:
    q = q.strip()
    if not q:
        return ""
    q = q.replace('"', " ")
    return f'"{q}"'


def add_memory_chunk(
    conn: sqlite3.Connection,
    body: str,
    *,
    session_id: str | None,
    source: str = "user",
    meta: dict | None = None,
) -> int:
    """摘要：插入一条记忆块记录。

    参数：
        conn: SQLite 连接。
        body: 记忆正文。
        session_id: 关联会话 ID（可为 None）。
        source: 来源标识。
        meta: 元数据字典，可含 content / memory_type / status / metadata 等。

    返回值：
        新记录的自增 ID。
    """
    body = body.strip()
    if not body:
        raise B2MemoryWriteError("empty memory body")
    now = time.time()
    meta = meta or {}
    content = str(meta.get("content") or body)
    memory_type = str(meta.get("memory_type") or "fact")
    status = str(meta.get("status") or "active")
    metadata = json.dumps(meta.get("metadata") or meta or {}, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO memory_chunks(session_id, content, body, memory_type, status, source, created_at, modified_at, metadata, meta_json) "
        "VALUES(?,?,?,?,?,?,?,?,?,?);",
        (session_id, content, body, memory_type, status, source, now, now, metadata, json.dumps(meta, ensure_ascii=False)),
    )
    rid = cur.lastrowid
    assert rid is not None
    chunk_id = int(rid)
    maybe_write_embedding(conn, chunk_id, body)
    return chunk_id


def search_memory(conn: sqlite3.Connection, query: str, limit: int = 8) -> list[MemoryHit]:
    """摘要：FTS 全文检索记忆（仅返回 status='active' 的记录）。"""
    q = _fts_escape_query(query)
    if not q:
        return []
    try:
        rows = conn.execute(
            "SELECT m.id, m.body, bm25(memory_fts) AS s "
            "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
            "WHERE memory_fts MATCH ? AND m.status = 'active' ORDER BY s LIMIT ?;",
            (q, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT m.id, m.body, NULL AS s "
            "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
            "WHERE memory_fts MATCH ? AND m.status = 'active' LIMIT ?;",
            (q, limit),
        ).fetchall()
    return [MemoryHit(id=int(r["id"]), body=r["body"], score=r["s"]) for r in rows]


def list_recent_memory(conn: sqlite3.Connection, limit: int = 20) -> list[MemoryHit]:
    """摘要：列出最近 active 记忆。"""
    rows = conn.execute(
        "SELECT id, body, NULL AS s FROM memory_chunks WHERE status = 'active' ORDER BY modified_at DESC, id DESC LIMIT ?;",
        (limit,),
    ).fetchall()
    return [MemoryHit(id=int(r["id"]), body=r["body"], score=r["s"]) for r in rows]


def list_memory_rows(
    conn: sqlite3.Connection,
    limit: int = 100,
    offset: int = 0,
    *,
    order_by: str = "modified_at DESC, id DESC",
) -> list[dict]:
    """摘要：列出记忆行（含所有状态），默认按 modified_at 倒序。

    参数：
        conn: SQLite 连接。
        limit: 每页条数。
        offset: 偏移量。
        order_by: 排序子句（默认 modified_at DESC, id DESC）。

    返回值：
        字典列表，每项含 id / session_id / content / body / memory_type /
        status / source / created_at / modified_at / metadata / meta。
    """
    rows = conn.execute(
        f"SELECT id, session_id, content, body, memory_type, status, source, created_at, modified_at, metadata, meta_json "
        f"FROM memory_chunks ORDER BY {order_by} LIMIT ? OFFSET ?;",
        (limit, offset),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "session_id": r["session_id"],
            "content": r["content"],
            "body": r["body"],
            "memory_type": r["memory_type"],
            "status": r["status"],
            "source": r["source"],
            "created_at": r["created_at"],
            "modified_at": r["modified_at"],
            "metadata": json.loads(r["metadata"] or "{}") if isinstance(r["metadata"], str) else {},
            "meta": json.loads(r["meta_json"] or "{}"),
        }
        for r in rows
    ]


def count_memory_rows(conn: sqlite3.Connection) -> int:
    """摘要：返回记忆库总行数。"""
    row = conn.execute("SELECT COUNT(*) AS c FROM memory_chunks;").fetchone()
    return int(row["c"])


def latest_profile_memory(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    rows = conn.execute(
        "SELECT body, meta_json FROM memory_chunks ORDER BY id ASC;"
    ).fetchall()
    profile: dict[str, dict[str, str]] = {"assistant": {}, "user": {}}
    for r in rows:
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except json.JSONDecodeError:
            continue
        target = str(meta.get("target") or "")
        field = str(meta.get("field") or "")
        value = str(meta.get("value") or "")
        memory_type = str(meta.get("memory_type") or "")
        if memory_type in {"agent_profile", "user_profile", "user_preference"} and target and field and value:
            profile.setdefault(target, {})[field] = value
    return profile


def delete_memory_chunk(conn: sqlite3.Connection, chunk_id: int) -> bool:
    """摘要：物理删除记忆块。"""
    cur = conn.execute("DELETE FROM memory_chunks WHERE id = ?;", (chunk_id,))
    return cur.rowcount > 0


def update_memory_chunk(conn: sqlite3.Connection, chunk_id: int, new_body: str) -> bool:
    new_body = new_body.strip()
    if not new_body:
        return False
    now = time.time()
    cur = conn.execute(
        "UPDATE memory_chunks SET body = ?, modified_at = ? WHERE id = ?;",
        (new_body, now, chunk_id),
    )
    if cur.rowcount > 0:
        maybe_write_embedding(conn, chunk_id, new_body)
    return cur.rowcount > 0


def invalidate_memory_chunk(conn: sqlite3.Connection, chunk_id: int) -> bool:
    """摘要：将记忆标记为 invalid（不删除）。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cur = conn.execute(
        "UPDATE memory_chunks SET status = 'invalid', modified_at = ? WHERE id = ?;",
        (now, chunk_id),
    )
    return cur.rowcount > 0


def restore_memory_chunk(conn: sqlite3.Connection, chunk_id: int) -> bool:
    """摘要：将记忆恢复为 active。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cur = conn.execute(
        "UPDATE memory_chunks SET status = 'active', modified_at = ? WHERE id = ?;",
        (now, chunk_id),
    )
    return cur.rowcount > 0


def maybe_extract_memory_commands(user_text: str) -> tuple[str, list[str]]:
    """摘要：解析 `#remember` 行并返回（聊天正文, 记忆行列表）。"""
    lines = user_text.splitlines()
    mem: list[str] = []
    kept: list[str] = []
    for line in lines:
        s = line.strip()
        if s.lower().startswith("#remember "):
            mem.append(s[len("#remember ") :].strip())
        else:
            kept.append(line)
    return "\n".join(kept).strip(), mem


def format_memory_block(hits: list[MemoryHit], max_chars: int = 1200) -> str:
    if not hits:
        return ""
    parts: list[str] = []
    n = 0
    for h in hits:
        line = f"- [{h.id}] {h.body}"
        if n + len(line) > max_chars:
            break
        parts.append(line)
        n += len(line) + 1
    if not parts:
        return ""
    return "Known memory snippets (editable by user; do not fabricate facts beyond them):\n" + "\n".join(parts)
