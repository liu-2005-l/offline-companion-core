from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import SemanticEvent
from offline_companion.runtime.storage_index.engine import connect


def make_event(event_id: str, *, event_type: str = "fact", importance: float = 1.0) -> SemanticEvent:
    return SemanticEvent(
        event_id=event_id,
        event_type=event_type,
        subject="user",
        content=f"事件 {event_id}",
        content_embedding=[1.0, 0.0],
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
    assert loaded.content_embedding == [1.0, 0.0]
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
        content_embedding=[0.0, 1.0],
        created_at=time.time(),
    ))

    results = repo.vector_search([1.0, 0.0], top_k=1)

    assert [event.event_id for event, _distance in results] == ["near"]


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
