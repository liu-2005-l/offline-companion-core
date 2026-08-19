from __future__ import annotations

import sqlite3
import time

from offline_companion.core.memory_lifecycle.decay import compute_decay_score, should_gc
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import SemanticEvent
from offline_companion.core.memory_lifecycle.idle_hook import MemoryIdleHook


class FakeExtractor:
    def __init__(self) -> None:
        self.calls = []

    def extract(self, messages, session_id, turn_range):
        self.calls.append((messages, session_id, turn_range))
        return [object()]


class FakeSessionRepo:
    def get_pending_extraction(self):
        return ("s1", [{"role": "user", "content": "残余消息"}], (11, 12))


def event(event_id: str, *, created_at: float, importance: float = 1.0, recall_count: int = 0) -> SemanticEvent:
    return SemanticEvent(
        event_id=event_id,
        event_type="fact",
        subject="user",
        content=event_id,
        created_at=created_at,
        importance=importance,
        recall_count=recall_count,
    )


def test_idle_hook_extracts_residual_messages_and_runs_gc() -> None:
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("stale", created_at=time.time() - 86400 * 1000))
    extractor = FakeExtractor()
    hook = MemoryIdleHook(extractor, repo, FakeSessionRepo())

    actions = hook.on_idle(300)

    assert extractor.calls[0][1:] == ("s1", (11, 12))
    assert "extracted 1 events from residual turns" in actions
    assert "marked 1 events as dormant" in actions
    assert repo.get("stale").status == "dormant"


def test_idle_hook_below_threshold_does_nothing() -> None:
    extractor = FakeExtractor()
    repo = EventRepository(sqlite3.connect(":memory:"))
    hook = MemoryIdleHook(extractor, repo, FakeSessionRepo())

    assert hook.on_idle(299) == []
    assert extractor.calls == []


def test_decay_preserves_recalled_events() -> None:
    old = event("old", created_at=time.time() - 86400 * 1000, recall_count=1)

    assert compute_decay_score(old) > 0
    assert not should_gc(old)
