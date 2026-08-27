from __future__ import annotations

import sqlite3
import time

from offline_companion.core.memory_lifecycle.event_recaller import EventRecaller
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import (
    CONTENT_EMBEDDING_DIMENSIONS,
    SemanticEvent,
)


def vector(index: int = 0) -> list[float]:
    values = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
    values[index] = 1.0
    return values


def event(event_id: str, content: str, *, importance: float = 3.0, related: list[str] | None = None) -> SemanticEvent:
    return SemanticEvent(
        event_id=event_id,
        event_type="fact",
        subject="user",
        content=content,
        content_embedding=vector(),
        importance=importance,
        related_events=related or [],
        created_at=time.time(),
    )


def make_repo() -> EventRepository:
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("a", "用户使用 Python", related=["b"]))
    repo.store(event("b", "用户完成本地项目", importance=4.0))
    repo.store(event("c", "用户喜欢茶", importance=1.0))
    return repo


def test_rrf_fuse_ranks_event_present_in_multiple_paths_first() -> None:
    scores = EventRecaller._rrf_fuse({"vector": ["a", "b"], "bm25": ["b", "a"], "hash": ["a"]})

    assert scores["a"] > scores["b"]


def test_recall_expands_related_events_and_returns_chronological_narrative() -> None:
    repo = make_repo()
    recaller = EventRecaller(
        repo,
        bm25=lambda _query: ["a"],
        embed_func=lambda _query: vector(),
    )

    results = recaller.recall("用户的技术背景", top_k=1)

    assert [item.event_id for item in results] == ["a", "b"]
    assert repo.get("a").recall_count == 1
    assert repo.get("b").recall_count == 1


def test_low_importance_related_event_is_not_expanded() -> None:
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("a", "用户使用 Python", related=["low"]))
    repo.store(event("low", "临时偏好", importance=2.0))
    recaller = EventRecaller(repo, embed_func=lambda _query: vector())

    results = recaller.recall("Python", top_k=1)

    assert [item.event_id for item in results] == ["a"]


def test_emotional_similarity_matches_identical_context() -> None:
    assert EventRecaller._emotional_similarity({"valence": 0.2, "arousal": 0.7}, 0.2, 0.7) == 1.0
    assert EventRecaller._emotional_similarity({"valence": 0.2, "arousal": 0.7}, -1.0, 0.0) < 0.5


def test_query_expansion_falls_back_to_original_on_llm_failure() -> None:
    class BrokenLlm:
        def generate(self, _prompt: str, *, temperature: float) -> str:
            raise RuntimeError("offline")

    recaller = EventRecaller(make_repo(), llm_backend=BrokenLlm())

    assert recaller._expand_query("原始查询") == ["原始查询"]
