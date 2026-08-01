from __future__ import annotations

import sqlite3
from pathlib import Path

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager


def test_add_memory_chunk_supports_legacy_updated_at_column(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE memory_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            source TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            meta_json TEXT,
            embedding_blob BLOB,
            content TEXT NOT NULL DEFAULT '',
            memory_type TEXT NOT NULL DEFAULT 'fact',
            status TEXT NOT NULL DEFAULT 'active',
            modified_at TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            embedding_model TEXT,
            embedding_dim INTEGER
        );
        """
    )

    chunk_id = MemoryLifecycleManager.add_memory_chunk(
        conn,
        "助手自画像：名字 = 立华奏",
        session_id="s1",
        source="semantic_auto",
        meta={"memory_type": "agent_profile"},
    )

    row = conn.execute(
        "SELECT body, updated_at, modified_at, memory_type FROM memory_chunks WHERE id = ?;",
        (chunk_id,),
    ).fetchone()
    assert row["body"] == "助手自画像：名字 = 立华奏"
    assert row["updated_at"] is not None
    assert row["modified_at"] != ""
    assert row["memory_type"] == "agent_profile"
