from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import (
    CONTENT_EMBEDDING_DIMENSIONS,
    SemanticEvent,
)
from offline_companion.runtime.storage_index.engine import connect


def vector(index: int = 0) -> list[float]:
    values = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
    values[index] = 1.0
    return values


def make_event(event_id: str, *, event_type: str = "fact", importance: float = 1.0) -> SemanticEvent:
    return SemanticEvent(
        event_id=event_id,
        event_type=event_type,
        subject="user",
        content=f"事件 {event_id}",
        content_embedding=vector(),
        importance=importance,
        created_at=time.time(),
        source_turns=[1, 2],
        related_events=["related-1"],
    )


def test_event_repository_creates_independent_schema(tmp_path: Path) -> None:
    conn = connect(tmp_path / "events.db")
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'semantic_events'").fetchone()
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'memory_chunks'").fetchone()
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "12"


def test_store_and_get_preserves_semantic_event_fields(tmp_path: Path) -> None:
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    event = make_event("e1", event_type="preference", importance=3.5)

    repo.store(event)
    loaded = repo.get("e1")

    assert loaded is not None
    assert loaded.event_type == "preference"
    assert loaded.content_embedding == vector()
    assert loaded.content_embedding_space == "hash_bow_768"
    assert loaded.source_turns == [1, 2]
    assert loaded.related_events == ["related-1"]
    assert loaded.importance == 3.5


def test_repository_filters_lifecycle_status(tmp_path: Path) -> None:
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    repo.store(make_event("active", importance=3.0))
    repo.store(make_event("old", importance=5.0))
    repo.mark_dormant("old")
    repo.mark_superseded("active", "new")

    assert repo.get_active() == []
    assert repo.get("old").status == "dormant"
    assert repo.get("active").superseded_by == "new"


def test_vector_search_returns_nearest_active_events(tmp_path: Path) -> None:
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    repo.store(make_event("near"))
    repo.store(SemanticEvent(
        event_id="far",
        event_type="fact",
        subject="user",
        content="远事件",
        content_embedding=vector(1),
        created_at=time.time(),
    ))

    results = repo.vector_search(vector(), top_k=1)

    assert [event.event_id for event, _distance in results] == ["near"]


def test_vector_search_logs_returned_count(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """摘要：vector_search 固定输出返回数 anchor，供回归诊断。"""
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    repo.store(make_event("near"))

    with caplog.at_level("INFO", logger="offline_companion.core.memory_lifecycle.event_repository"):
        results = repo.vector_search(vector(), top_k=1)

    assert len(results) == 1
    assert "semantic event vector_search returned 1 events for top_k=1 candidates=1 space=hash_bow_768" in caplog.text


def test_store_rejects_non_768_dimension_embedding(tmp_path: Path) -> None:
    """摘要：向量维度错误在仓储写入阶段 fail-fast，不推迟到搜索阶段。"""
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    event = make_event("bad")
    event.content_embedding[:] = [1.0, 0.0]

    with pytest.raises(ValueError, match="768 dimensions"):
        repo.store(event)


def test_store_duplicate_event_id_raises_integrity_error(tmp_path: Path) -> None:
    """摘要：仓储层不吞同 ID 冲突，由调用方负责去重策略。"""
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    repo.store(make_event("dup"))

    with pytest.raises(sqlite3.IntegrityError):
        repo.store(make_event("dup"))


def test_vector_search_ignores_mismatched_embedding_space(tmp_path: Path) -> None:
    """摘要：召回只比较同一 embedding 空间，避免同维混源产生垃圾分。"""
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    repo.store(make_event("hash"))
    repo.store(SemanticEvent(
        event_id="semantic",
        event_type="fact",
        subject="user",
        content="语义空间事件",
        content_embedding=vector(),
        content_embedding_space="semantic_onnx_768",
        created_at=time.time(),
    ))

    results = repo.vector_search(vector(), embedding_space="semantic_onnx_768")

    assert [event.event_id for event, _distance in results] == ["semantic"]


def test_update_recall_stats_increments_counter(tmp_path: Path) -> None:
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    repo.store(make_event("e1"))
    repo.update_recall_stats("e1")
    loaded = repo.get("e1")

    assert loaded.recall_count == 1
    assert loaded.last_recalled_at > 0


@pytest.mark.parametrize(
    "field,value",
    [("event_type", "unknown"), ("emotional_valence", 2.0), ("importance", 6.0)],
)
def test_semantic_event_rejects_invalid_fields(field: str, value: object) -> None:
    values = {
        "event_id": "e1",
        "event_type": "fact",
        "subject": "user",
        "content": "content",
        field: value,
    }
    event = SemanticEvent(**values)

    with pytest.raises(ValueError):
        event.validate()
