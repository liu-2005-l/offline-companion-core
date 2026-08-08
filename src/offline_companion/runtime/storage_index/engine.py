"""engine：SQLite 连接、迁移与消息访问。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from offline_companion.shared.types import MessageRow

SCHEMA_VERSION = 10


def connect(db_path: Path) -> sqlite3.Connection:
    """摘要：打开数据库并执行迁移。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.text_factory = str
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
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
    version = int(row["value"]) if row else 0
    if version < 1:
        _init_v1(conn)
        version = 1
    if version < 2:
        _init_v2(conn)
        version = 2
    if version < 3:
        _init_v3(conn)
        version = 3
    if version < 4:
        _init_v4(conn)
        version = 4
    if version < 5:
        _init_v5(conn)
        version = 5
    if version < 6:
        _init_v6(conn)
        version = 6
    if version < 7:
        _init_v7(conn)
        version = 7
    if version < 8:
        _init_v8(conn)
        version = 8
    if version < 9:
        _init_v9(conn)
        version = 9
    if version < 10:
        _init_v10(conn)
        version = 10
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
        (str(version),),
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
            content TEXT NOT NULL DEFAULT '',
            emotion TEXT,
            created_at REAL NOT NULL,
            meta_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

        CREATE TABLE IF NOT EXISTS memory_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            content TEXT NOT NULL,
            body TEXT,
            memory_type TEXT NOT NULL DEFAULT 'fact',
            status TEXT NOT NULL DEFAULT 'active',
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            meta_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_memory_created ON memory_chunks(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_modified ON memory_chunks(modified_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_type_status ON memory_chunks(memory_type, status);

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            content,
            body,
            content='memory_chunks',
            content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_chunks BEGIN
            INSERT INTO memory_fts(rowid, content, body)
            VALUES (new.id, new.content, COALESCE(new.body, new.content));
        END;
        CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_chunks BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, content, body)
            VALUES('delete', old.id, old.content, COALESCE(old.body, old.content));
        END;
        CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_chunks BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, content, body)
            VALUES('delete', old.id, old.content, COALESCE(old.body, old.content));
            INSERT INTO memory_fts(rowid, content, body)
            VALUES (new.id, new.content, COALESCE(new.body, new.content));
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
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_chunks);").fetchall()}
    if "embedding_blob" not in cols:
        conn.execute("ALTER TABLE memory_chunks ADD COLUMN embedding_blob BLOB;")


def _init_v4(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_chunks);").fetchall()}
    required = {
        "content": "TEXT NOT NULL DEFAULT ''",
        "body": "TEXT",
        "memory_type": "TEXT NOT NULL DEFAULT 'fact'",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "source": "TEXT NOT NULL DEFAULT 'user_explicit'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "modified_at": "TEXT NOT NULL DEFAULT ''",
        "metadata": "TEXT NOT NULL DEFAULT '{}'",
        "meta_json": "TEXT",
    }
    for name, ddl in required.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE memory_chunks ADD COLUMN {name} {ddl};")


def _init_v5(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_chunks);").fetchall()}
    required = {
        "embedding_blob": "BLOB",
        "embedding_model": "TEXT",
        "embedding_dim": "INTEGER",
    }
    for name, ddl in required.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE memory_chunks ADD COLUMN {name} {ddl};")


def _init_v6(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages);").fetchall()}
    if "emotion" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN emotion TEXT;")


def _init_v7(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS job_tasks (
            task_id TEXT PRIMARY KEY,
            skill_name TEXT NOT NULL,
            task_type TEXT NOT NULL,
            cron_expr TEXT,
            delay_until REAL,
            event_condition TEXT,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'normal',
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            queue_type TEXT NOT NULL DEFAULT 'background',
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            last_heartbeat TEXT,
            heartbeat_timeout_sec INTEGER NOT NULL DEFAULT 300,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            idempotency_key TEXT,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_job_tasks_status ON job_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_job_tasks_session ON job_tasks(session_id);
        CREATE INDEX IF NOT EXISTS idx_job_tasks_delay_until
            ON job_tasks(delay_until) WHERE delay_until IS NOT NULL;

        CREATE TABLE IF NOT EXISTS message_execution_records (
            idempotency_key TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            handler_namespace TEXT NOT NULL,
            status TEXT NOT NULL,
            result TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_message_execution_session
            ON message_execution_records(session_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS dead_letter_queue (
            dlq_id TEXT PRIMARY KEY,
            original_message_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            queue_type TEXT NOT NULL,
            handler_namespace TEXT NOT NULL,
            original_payload TEXT NOT NULL,
            error TEXT NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            resolved_at TEXT,
            resolved_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dlq_session_created
            ON dead_letter_queue(session_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_dlq_resolved
            ON dead_letter_queue(resolved, created_at DESC);
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(job_tasks);").fetchall()}
    if "error" not in cols:
        conn.execute("ALTER TABLE job_tasks ADD COLUMN error TEXT;")


def _init_v8(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS extension_status (
            extension_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at REAL NOT NULL
        );
        """
    )


def _init_v9(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS personas (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar TEXT NOT NULL DEFAULT '',
            desc TEXT NOT NULL DEFAULT '',
            ocean_json TEXT NOT NULL DEFAULT '[]',
            traits_json TEXT NOT NULL DEFAULT '[]',
            anchor TEXT NOT NULL DEFAULT '',
            system_prompt TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}',
            active INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_personas_single_active
            ON personas(active) WHERE active = 1;
        """
    )


def _init_v10(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS plans (
            plan_id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plan_steps (
            plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
            step_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            deps_json TEXT NOT NULL DEFAULT '[]',
            risk TEXT NOT NULL DEFAULT 'low',
            status TEXT NOT NULL DEFAULT 'pending',
            requires_auth INTEGER NOT NULL DEFAULT 0,
            result TEXT,
            error TEXT,
            consent_request_id TEXT,
            updated_at REAL NOT NULL,
            PRIMARY KEY(plan_id, step_id)
        );
        CREATE INDEX IF NOT EXISTS idx_plan_steps_plan ON plan_steps(plan_id, step_id);
        """
    )


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
    emotion: str | None = None,
) -> int:
    message_id = conn.execute(
        "INSERT INTO messages(session_id, role, content, emotion, created_at, meta_json) "
        "VALUES(?,?,?,?,?,?);",
        (session_id, role, content, emotion, time.time(), json.dumps(meta or {})),
    ).lastrowid
    assert message_id is not None
    touch_session(conn, session_id)
    return int(message_id)


def clear_session_messages(conn: sqlite3.Connection, session_id: str) -> int:
    cursor = conn.execute("DELETE FROM messages WHERE session_id = ?;", (session_id,))
    touch_session(conn, session_id)
    return int(cursor.rowcount)


def recent_messages(conn: sqlite3.Connection, session_id: str, limit: int) -> list[MessageRow]:
    rows = conn.execute(
        "SELECT role, content, created_at, meta_json FROM messages "
        "WHERE session_id = ? ORDER BY id DESC LIMIT ?;",
        (session_id, limit),
    ).fetchall()
    messages: list[MessageRow] = []
    for row in reversed(rows):
        messages.append(
            MessageRow(
                role=row["role"],
                content=row["content"],
                created_at=float(row["created_at"]),
                meta=json.loads(row["meta_json"] or "{}"),
            )
        )
    return messages
