"""engine：SQLite 连接、迁移与会话/消息表访问（C2）。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from offline_companion.shared.types import MessageRow

SCHEMA_VERSION = 3


def connect(db_path: Path) -> sqlite3.Connection:
    """摘要：打开数据库并执行迁移。

    参数：
        db_path: SQLite 文件路径。

    返回值：
        已启用 foreign_keys 的连接。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    ver = int(row["value"]) if row else 0
    if ver < 1:
        _init_v1(conn)
        ver = 1
    if ver < 2:
        _init_v2(conn)
        ver = 2
    if ver < 3:
        _init_v3(conn)
        ver = 3
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
        (str(ver),),
    )


def _init_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            persona_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            meta_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

        CREATE TABLE IF NOT EXISTS memory_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            source TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            meta_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_memory_created ON memory_chunks(created_at DESC);

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            body,
            content='memory_chunks',
            content_rowid='id',
            tokenize = 'unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_chunks BEGIN
            INSERT INTO memory_fts(rowid, body) VALUES (new.id, new.body);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_chunks BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, body) VALUES('delete', old.id, old.body);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_chunks BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, body) VALUES('delete', old.id, old.body);
            INSERT INTO memory_fts(rowid, body) VALUES (new.id, new.body);
        END;

        CREATE TABLE IF NOT EXISTS consent_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT,
            artifact_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """
    )


def _init_v2(conn: sqlite3.Connection) -> None:
    """摘要：Sprint 4.2 记忆摘要草稿表（与 memory_chunks 隔离）。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            meta_json TEXT,
            created_at REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE INDEX IF NOT EXISTS idx_memory_drafts_session
            ON memory_drafts(session_id, status, created_at DESC);
        """
    )


def _init_v3(conn: sqlite3.Connection) -> None:
    """摘要：Sprint 5.1 记忆块可选向量 BLOB。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_chunks);").fetchall()}
    if "embedding_blob" not in cols:
        conn.execute("ALTER TABLE memory_chunks ADD COLUMN embedding_blob BLOB;")


def new_session(conn: sqlite3.Connection, session_id: str, persona_id: str, title: str | None) -> None:
    now = time.time()
    conn.execute(
        "INSERT INTO sessions(id, title, persona_id, created_at, updated_at) VALUES(?,?,?,?,?);",
        (session_id, title, persona_id, now, now),
    )


def touch_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?;", (time.time(), session_id))


def append_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    meta: dict[str, Any] | None = None,
) -> int:
    mid = conn.execute(
        "INSERT INTO messages(session_id, role, content, created_at, meta_json) "
        "VALUES(?,?,?,?,?);",
        (session_id, role, content, time.time(), json.dumps(meta or {})),
    ).lastrowid
    assert mid is not None
    touch_session(conn, session_id)
    return int(mid)


def recent_messages(conn: sqlite3.Connection, session_id: str, limit: int) -> list[MessageRow]:
    rows = conn.execute(
        "SELECT role, content, created_at, meta_json FROM messages "
        "WHERE session_id = ? ORDER BY id DESC LIMIT ?;",
        (session_id, limit),
    ).fetchall()
    out: list[MessageRow] = []
    for r in reversed(rows):
        out.append(
            MessageRow(
                role=r["role"],
                content=r["content"],
                created_at=float(r["created_at"]),
                meta=json.loads(r["meta_json"] or "{}"),
            )
        )
    return out
