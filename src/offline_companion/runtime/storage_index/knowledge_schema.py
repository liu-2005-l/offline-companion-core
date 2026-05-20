"""knowledge_schema：知识库 DDL 与迁移（C2；独立 knowledge.db）。"""

from __future__ import annotations

import sqlite3

KNOWLEDGE_SCHEMA_VERSION = 1


def migrate_knowledge_db(conn: sqlite3.Connection) -> None:
    """摘要：确保知识库 schema 为当前版本。"""
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
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
            (str(KNOWLEDGE_SCHEMA_VERSION),),
        )


def _init_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source_uri TEXT NOT NULL,
            license_note TEXT,
            ingested_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            meta_json TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
            body,
            content='knowledge_chunks',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN
            INSERT INTO knowledge_fts(rowid, body) VALUES (new.id, new.body);
        END;
        CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN
            INSERT INTO knowledge_fts(knowledge_fts, rowid, body) VALUES ('delete', old.id, old.body);
        END;
        CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE ON knowledge_chunks BEGIN
            INSERT INTO knowledge_fts(knowledge_fts, rowid, body) VALUES ('delete', old.id, old.body);
            INSERT INTO knowledge_fts(rowid, body) VALUES (new.id, new.body);
        END;

        CREATE TABLE IF NOT EXISTS knowledge_search_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            query TEXT NOT NULL,
            hit_ids_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """
    )
