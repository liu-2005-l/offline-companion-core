"""fts_ops：记忆块与 FTS 检索（B2 子模块；仅 SQLite）。"""

from __future__ import annotations

import json
import sqlite3
import time

from offline_companion.shared.types import MemoryHit


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
    body = body.strip()
    if not body:
        raise ValueError("empty memory body")
    now = time.time()
    cur = conn.execute(
        "INSERT INTO memory_chunks(session_id, source, body, created_at, updated_at, meta_json) "
        "VALUES(?,?,?,?,?,?);",
        (session_id, source, body, now, now, json.dumps(meta or {})),
    )
    rid = cur.lastrowid
    assert rid is not None
    return int(rid)


def search_memory(conn: sqlite3.Connection, query: str, limit: int = 8) -> list[MemoryHit]:
    q = _fts_escape_query(query)
    if not q:
        return []
    try:
        rows = conn.execute(
            "SELECT m.id, m.body, bm25(memory_fts) AS s "
            "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
            "WHERE memory_fts MATCH ? ORDER BY s LIMIT ?;",
            (q, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            "SELECT m.id, m.body, NULL AS s "
            "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
            "WHERE memory_fts MATCH ? LIMIT ?;",
            (q, limit),
        ).fetchall()
    return [MemoryHit(id=int(r["id"]), body=r["body"], score=r["s"]) for r in rows]


def list_recent_memory(conn: sqlite3.Connection, limit: int = 20) -> list[MemoryHit]:
    rows = conn.execute(
        "SELECT id, body, NULL AS s FROM memory_chunks ORDER BY id DESC LIMIT ?;",
        (limit,),
    ).fetchall()
    return [MemoryHit(id=int(r["id"]), body=r["body"], score=r["s"]) for r in rows]


def delete_memory_chunk(conn: sqlite3.Connection, chunk_id: int) -> bool:
    cur = conn.execute("DELETE FROM memory_chunks WHERE id = ?;", (chunk_id,))
    return cur.rowcount > 0


def update_memory_chunk(conn: sqlite3.Connection, chunk_id: int, new_body: str) -> bool:
    new_body = new_body.strip()
    if not new_body:
        return False
    cur = conn.execute(
        "UPDATE memory_chunks SET body = ?, updated_at = ? WHERE id = ?;",
        (new_body, time.time(), chunk_id),
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
