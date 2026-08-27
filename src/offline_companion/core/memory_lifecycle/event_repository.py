"""语义事件的 SQLite 持久化与基础生命周期操作。"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import replace

from offline_companion.shared.deterministic_embedding import (
    blob_to_vector,
    cosine_similarity,
    vector_to_blob,
)

from .event_types import SemanticEvent

logger = logging.getLogger(__name__)


class EventRepository:
    """摘要：管理 ``semantic_events`` 表及其内容向量索引。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """摘要：绑定已初始化的 SQLite 连接并确保事件表存在。"""
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS semantic_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                content_embedding BLOB,
                emotional_valence REAL NOT NULL DEFAULT 0.0,
                emotional_arousal REAL NOT NULL DEFAULT 0.0,
                importance REAL NOT NULL DEFAULT 1.0,
                temporal_marker TEXT NOT NULL DEFAULT '',
                source_turns TEXT NOT NULL DEFAULT '[]',
                related_events TEXT NOT NULL DEFAULT '[]',
                superseded_by TEXT,
                created_at REAL NOT NULL,
                last_recalled_at REAL NOT NULL DEFAULT 0.0,
                recall_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE INDEX IF NOT EXISTS idx_semantic_events_type
                ON semantic_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_semantic_events_status
                ON semantic_events(status);
            CREATE INDEX IF NOT EXISTS idx_semantic_events_importance
                ON semantic_events(importance DESC);
            CREATE INDEX IF NOT EXISTS idx_semantic_events_created
                ON semantic_events(created_at DESC);
            """
        )

    def store(self, event: SemanticEvent) -> None:
        """摘要：插入一条语义事件及其可选向量。

        异常：
            ValueError: 事件字段非法时抛出。
            sqlite3.Error: SQLite 写入失败时抛出。
        """
        event.validate()
        created_at = event.created_at or time.time()
        self._conn.execute(
            """
            INSERT INTO semantic_events (
                event_id, event_type, subject, content, content_embedding,
                emotional_valence, emotional_arousal, importance,
                temporal_marker, source_turns, related_events, superseded_by,
                created_at, last_recalled_at, recall_count, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id, event.event_type, event.subject, event.content,
                vector_to_blob(event.content_embedding) if event.content_embedding else None,
                event.emotional_valence, event.emotional_arousal, event.importance,
                event.temporal_marker, json.dumps(event.source_turns),
                json.dumps(event.related_events), event.superseded_by, created_at,
                event.last_recalled_at, event.recall_count, event.status,
            ),
        )
        self._conn.commit()

    def get(self, event_id: str) -> SemanticEvent | None:
        """摘要：按 ID 读取一条事件。"""
        row = self._conn.execute(
            "SELECT * FROM semantic_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return _row_to_event(row) if row else None

    def get_active(self, limit: int = 1000) -> list[SemanticEvent]:
        """摘要：按重要性和创建时间读取 active 事件。"""
        rows = self._conn.execute(
            "SELECT * FROM semantic_events WHERE status = 'active' "
            "ORDER BY importance DESC, created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def get_by_type(self, event_type: str, limit: int = 50) -> list[SemanticEvent]:
        """摘要：按事件类型读取 active 事件。"""
        rows = self._conn.execute(
            "SELECT * FROM semantic_events WHERE event_type = ? AND status = 'active' "
            "ORDER BY importance DESC, created_at DESC LIMIT ?", (event_type, limit)
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def get_recent(self, days: int = 30, limit: int = 100) -> list[SemanticEvent]:
        """摘要：读取最近指定天数内的 active 事件。"""
        cutoff = time.time() - days * 86400
        rows = self._conn.execute(
            "SELECT * FROM semantic_events WHERE created_at >= ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT ?", (cutoff, limit)
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def vector_search(
        self, query_embedding: list[float], top_k: int = 20
    ) -> list[tuple[SemanticEvent, float]]:
        """摘要：在 active 事件向量上执行余弦相似度扫描并返回距离升序结果。"""
        if top_k <= 0:
            return []
        rows = self._conn.execute(
            "SELECT * FROM semantic_events "
            "WHERE status = 'active' AND content_embedding IS NOT NULL"
        ).fetchall()
        ranked: list[tuple[SemanticEvent, float]] = []
        for row in rows:
            event = _row_to_event(row)
            vector = event.content_embedding
            if vector is None:
                continue
            similarity = cosine_similarity(query_embedding, vector)
            ranked.append((event, 1.0 - similarity))
        ranked.sort(key=lambda item: item[1])
        results = ranked[:top_k]
        logger.info(
            "semantic event vector_search returned %d events for top_k=%d candidates=%d",
            len(results),
            top_k,
            len(ranked),
        )
        return results

    def update_recall_stats(self, event_id: str) -> None:
        """摘要：记录一次成功召回。"""
        self._conn.execute(
            "UPDATE semantic_events SET recall_count = recall_count + 1, "
            "last_recalled_at = ? WHERE event_id = ?", (time.time(), event_id)
        )
        self._conn.commit()

    def mark_superseded(self, old_id: str, new_id: str) -> None:
        """摘要：将旧事件标记为由新事件替代。"""
        self._conn.execute(
            "UPDATE semantic_events SET status = 'superseded', superseded_by = ? "
            "WHERE event_id = ?", (new_id, old_id)
        )
        self._conn.commit()

    def mark_dormant(self, event_id: str) -> None:
        """摘要：将事件标记为 dormant，使其不再参与 active 召回。"""
        self._conn.execute(
            "UPDATE semantic_events SET status = 'dormant' WHERE event_id = ?",
            (event_id,),
        )
        self._conn.commit()

    def update_fields(self, event_id: str, fields: dict[str, object]) -> bool:
        """摘要：更新允许用户管理的事件字段并重新校验。"""
        current = self.get(event_id)
        if current is None:
            return False
        allowed = {
            "event_type", "subject", "content", "emotional_valence",
            "emotional_arousal", "importance", "temporal_marker",
        }
        changes = {key: value for key, value in fields.items() if key in allowed}
        if not changes:
            return False
        if "content" in changes:
            changes["content_embedding"] = None
        updated = replace(current, **changes)
        updated.validate()
        self._conn.execute(
            """
            UPDATE semantic_events SET event_type = ?, subject = ?, content = ?,
                content_embedding = ?, emotional_valence = ?, emotional_arousal = ?,
                importance = ?, temporal_marker = ?, status = ? WHERE event_id = ?
            """,
            (
                updated.event_type, updated.subject, updated.content,
                vector_to_blob(updated.content_embedding) if updated.content_embedding else None,
                updated.emotional_valence, updated.emotional_arousal, updated.importance,
                updated.temporal_marker, updated.status, event_id,
            ),
        )
        self._conn.commit()
        return True


def _row_to_event(row: sqlite3.Row) -> SemanticEvent:
    """摘要：把 SQLite 行安全转换成不可变事件对象。"""
    return SemanticEvent(
        event_id=str(row["event_id"]),
        event_type=str(row["event_type"]),
        subject=str(row["subject"]),
        content=str(row["content"]),
        content_embedding=blob_to_vector(row["content_embedding"]),
        emotional_valence=float(row["emotional_valence"]),
        emotional_arousal=float(row["emotional_arousal"]),
        importance=float(row["importance"]),
        temporal_marker=str(row["temporal_marker"]),
        source_turns=[int(value) for value in json.loads(row["source_turns"])],
        related_events=[str(value) for value in json.loads(row["related_events"])],
        superseded_by=row["superseded_by"],
        created_at=float(row["created_at"]),
        last_recalled_at=float(row["last_recalled_at"]),
        recall_count=int(row["recall_count"]),
        status=str(row["status"]),
    )
