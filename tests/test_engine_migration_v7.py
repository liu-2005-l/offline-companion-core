from __future__ import annotations

import sqlite3
from pathlib import Path

from offline_companion.runtime.storage_index.engine import SCHEMA_VERSION, connect


def _create_v6_db(path: Path) -> None:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
    conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '6');")
    conn.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            persona_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            emotion TEXT,
            created_at REAL NOT NULL,
            meta_json TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE memory_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            content TEXT NOT NULL,
            body TEXT,
            memory_type TEXT NOT NULL DEFAULT 'fact',
            status TEXT NOT NULL DEFAULT 'active',
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            meta_json TEXT,
            embedding_blob BLOB,
            embedding_model TEXT,
            embedding_dim INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO sessions(id, title, persona_id, created_at, updated_at) VALUES('s-1', 't', 'default', 1.0, 1.0);"
    )
    conn.execute(
        "INSERT INTO messages(session_id, role, content, emotion, created_at, meta_json) VALUES('s-1', 'user', 'hi', NULL, 1.0, '{}');"
    )
    conn.close()


def test_engine_migrates_v6_to_current_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "companion.db"
    _create_v6_db(db_path)

    conn = connect(db_path)
    version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version';").fetchone()[0]
    assert int(version) == SCHEMA_VERSION

    table_names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';").fetchall()
    }
    assert {
        "job_tasks",
        "message_execution_records",
        "dead_letter_queue",
        "extension_status",
        "personas",
        "plans",
        "plan_steps",
        "stream_events",
    } <= table_names
    job_task_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(job_tasks);").fetchall()
    }
    assert "error" in job_task_columns
    message_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(messages);").fetchall()
    }
    assert "status" in message_columns

    session_count = conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0]
    message_count = conn.execute("SELECT COUNT(*) FROM messages;").fetchone()[0]
    assert int(session_count) == 1
    assert int(message_count) == 1
