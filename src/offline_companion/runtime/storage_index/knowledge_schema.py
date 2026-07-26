"""knowledge_schema：知识库 DDL 与迁移（C2；独立 knowledge.db）。"""

from __future__ import annotations

import sqlite3

from offline_companion.shared.deterministic_embedding import embed_text, vector_to_blob

_KNOWLEDGE_EMBEDDING_DIMENSIONS = 128
_KNOWLEDGE_EMBEDDING_MODEL = "deterministic_hash_bow_v1"
KNOWLEDGE_SCHEMA_VERSION = 2


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
        ver = 1
    if ver < 2:
        _migrate_v2(conn)
        ver = 2
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
        (str(ver),),
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


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """摘要：为知识块补充向量存储字段并回填历史数据。"""
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(knowledge_chunks);").fetchall()
    }
    if "embedding_blob" not in cols:
        conn.execute("ALTER TABLE knowledge_chunks ADD COLUMN embedding_blob BLOB;")
    if "embedding_model" not in cols:
        conn.execute("ALTER TABLE knowledge_chunks ADD COLUMN embedding_model TEXT;")
    if "embedding_dim" not in cols:
        conn.execute("ALTER TABLE knowledge_chunks ADD COLUMN embedding_dim INTEGER;")

    rows = conn.execute(
        "SELECT id, body FROM knowledge_chunks WHERE embedding_blob IS NULL OR embedding_dim IS NULL;"
    ).fetchall()
    for row in rows:
        vec = embed_text(str(row["body"]), dimensions=_KNOWLEDGE_EMBEDDING_DIMENSIONS)
        conn.execute(
            """
            UPDATE knowledge_chunks
            SET embedding_blob = ?, embedding_model = ?, embedding_dim = ?
            WHERE id = ?;
            """,
            (
                vector_to_blob(vec),
                _KNOWLEDGE_EMBEDDING_MODEL,
                _KNOWLEDGE_EMBEDDING_DIMENSIONS,
                int(row["id"]),
            ),
        )
