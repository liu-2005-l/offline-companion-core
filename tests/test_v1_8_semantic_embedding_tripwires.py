"""摘要：v1.8.0 真 semantic embedding 开工前的 degraded 预注册哨兵。"""

from __future__ import annotations

import sqlite3

import pytest

from offline_companion.core.memory_lifecycle.event_recaller import EventRecaller
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import (
    CONTENT_EMBEDDING_DIMENSIONS,
    SemanticEvent,
)
from offline_companion.shared.deterministic_embedding import embed_text


R43_R46_PARAPHRASE_TRIPWIRES = (
    ("R43", "canine companion naps beside keyboard", "dog sleeps near laptop"),
    ("R44", "relocate shanghai next spring", "move magiccity after winter"),
    ("R45", "cilantro causes nausea", "avoid coriander garnish"),
    ("R46", "offline default privacy policy", "network access requires consent"),
)


def _repo_with_event(event_id: str, content: str) -> EventRepository:
    """摘要：构造只含一条语义事件的内存仓库。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(
        SemanticEvent(
            event_id=event_id,
            event_type="fact",
            subject="user",
            content=content,
            content_embedding=embed_text(content, dimensions=CONTENT_EMBEDDING_DIMENSIONS),
            importance=4.0,
            created_at=1.0,
        )
    )
    return repo


@pytest.mark.parametrize(("case_id", "stored_content", "query"), R43_R46_PARAPHRASE_TRIPWIRES)
def test_r43_r46_paraphrase_recall_tripwires_are_degraded(
    case_id: str,
    stored_content: str,
    query: str,
) -> None:
    """摘要：R43-R46 先钉当前 hash-bow 语义改写召回降级基线。"""
    assert EventRecaller._tokenize(stored_content) & EventRecaller._tokenize(query) == set()
    repo = _repo_with_event(case_id, stored_content)

    results = EventRecaller(
        repo,
        embed_func=lambda text: embed_text(text, dimensions=CONTENT_EMBEDDING_DIMENSIONS),
    ).recall(query, top_k=5)

    assert results == []
    assert repo.get(case_id).recall_count == 0


def test_related_semantic_auto_association_is_degraded_until_true_embedding() -> None:
    """摘要：无显式 related_events 时不伪装 0.70 语义关联已经实现。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(
        SemanticEvent(
            event_id="primary",
            event_type="fact",
            subject="user",
            content="canine companion naps beside keyboard",
            content_embedding=embed_text("canine companion naps beside keyboard", dimensions=CONTENT_EMBEDDING_DIMENSIONS),
            importance=4.0,
            created_at=1.0,
        )
    )
    repo.store(
        SemanticEvent(
            event_id="semantic-related",
            event_type="fact",
            subject="user",
            content="dog sleeps near laptop",
            content_embedding=embed_text("dog sleeps near laptop", dimensions=CONTENT_EMBEDDING_DIMENSIONS),
            importance=4.0,
            created_at=2.0,
        )
    )

    results = EventRecaller(
        repo,
        embed_func=lambda text: embed_text(text, dimensions=CONTENT_EMBEDDING_DIMENSIONS),
    ).recall("canine companion naps beside keyboard", top_k=5)

    assert [event.event_id for event in results] == ["primary"]
    assert repo.get("primary").recall_count == 1
    assert repo.get("semantic-related").recall_count == 0

