from __future__ import annotations

import logging
import math
import sqlite3
import time

import pytest

from offline_companion.core.memory_lifecycle.event_extractor import HASH_BOW_DUPLICATE_THRESHOLD
from offline_companion.core.memory_lifecycle.event_recaller import (
    HASH_BOW_RECALL_THRESHOLD,
    RRF_K,
    EventRecaller,
    SEMANTIC_RECALL_THRESHOLD,
    format_event_narrative,
    recall_threshold_for_space,
)
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import (
    CONTENT_EMBEDDING_DIMENSIONS,
    SemanticEvent,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import OceanVector, Persona


def vector(index: int = 0) -> list[float]:
    values = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
    values[index] = 1.0
    return values


def event(
    event_id: str,
    content: str,
    *,
    importance: float = 3.0,
    related: list[str] | None = None,
    vector_index: int = 0,
    event_type: str = "fact",
    created_at: float | None = None,
    emotional_valence: float = 0.0,
    emotional_arousal: float = 0.0,
    recall_count: int = 0,
    status: str = "active",
    content_embedding_space: str = "hash_bow_768",
) -> SemanticEvent:
    return SemanticEvent(
        event_id=event_id,
        event_type=event_type,
        subject="user",
        content=content,
        content_embedding=vector(vector_index),
        content_embedding_space=content_embedding_space,
        emotional_valence=emotional_valence,
        emotional_arousal=emotional_arousal,
        importance=importance,
        related_events=related or [],
        created_at=time.time() if created_at is None else created_at,
        recall_count=recall_count,
        status=status,
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


def test_rrf_fuse_uses_zero_based_rank_and_configurable_k() -> None:
    """摘要：RRF 分数使用 rank=0 起算，并受 k 常数控制。"""
    scores = EventRecaller._rrf_fuse({"vector": ["a"], "bm25": ["a"], "hash_bow": ["a"]})
    mixed = EventRecaller._rrf_fuse({"vector": ["a"], "bm25": ["x", "a"]})
    missing_path = EventRecaller._rrf_fuse({"vector": ["a"], "bm25": ["x", "y", "a"]})
    steep = EventRecaller._rrf_fuse({"vector": ["a", "b"]}, k=10)
    flat = EventRecaller._rrf_fuse({"vector": ["a", "b"]}, k=RRF_K)

    assert scores["a"] == pytest.approx(3 / RRF_K)
    assert mixed["a"] == pytest.approx(1 / RRF_K + 1 / (RRF_K + 1))
    assert missing_path["a"] == pytest.approx(1 / RRF_K + 1 / (RRF_K + 2))
    assert steep["a"] - steep["b"] > flat["a"] - flat["b"]
    assert EventRecaller._rrf_fuse({}) == {}


def test_recall_uses_vector_bm25_and_hash_bow_paths() -> None:
    """摘要：三条召回路径都能独立产生候选。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("vector-hit", "向量命中", vector_index=1))
    repo.store(event("bm25-hit", "BM25 命中", vector_index=2))
    repo.store(event("bow-hit", "hash-bow 命中", vector_index=3))

    assert [
        item.event_id
        for item in EventRecaller(repo, embed_func=lambda _query: vector(1)).recall("向量", top_k=1)
    ] == ["vector-hit"]
    assert [
        item.event_id
        for item in EventRecaller(repo, bm25=lambda _query: ["bm25-hit"]).recall("无词面", top_k=1)
    ] == ["bm25-hit"]
    assert [
        item.event_id
        for item in EventRecaller(repo, hash_bow=lambda _query: ["bow-hit"]).recall("无词面", top_k=1)
    ] == ["bow-hit"]


def test_vector_path_filters_below_hash_bow_recall_threshold() -> None:
    """摘要：Session 注入使用的 vector 路不把低相似事件静默注入上下文。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("hit", "向量命中", vector_index=1))
    repo.store(event("miss", "无关事件", vector_index=2))

    results = EventRecaller(repo, embed_func=lambda _query: vector(1)).recall("向量", top_k=5)

    assert HASH_BOW_RECALL_THRESHOLD == HASH_BOW_DUPLICATE_THRESHOLD == 0.50
    assert [item.event_id for item in results] == ["hit"]


def test_vector_path_uses_semantic_recall_threshold_for_onnx_space() -> None:
    """摘要：真 semantic 召回使用独立阈值，零 FP 侧不沿用 hash-bow 0.50。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    near_miss = [0.575, math.sqrt(1.0 - 0.575**2), *([0.0] * (CONTENT_EMBEDDING_DIMENSIONS - 2))]
    hit = [0.581, math.sqrt(1.0 - 0.581**2), *([0.0] * (CONTENT_EMBEDDING_DIMENSIONS - 2))]
    repo.store(
        SemanticEvent(
            event_id="near-miss",
            event_type="fact",
            subject="user",
            content="semantic-only-a",
            content_embedding=near_miss,
            content_embedding_space="semantic_onnx_768",
            importance=5.0,
            created_at=time.time(),
        )
    )
    repo.store(
        SemanticEvent(
            event_id="hit",
            event_type="fact",
            subject="user",
            content="semantic-only-b",
            content_embedding=hit,
            content_embedding_space="semantic_onnx_768",
            importance=5.0,
            created_at=time.time(),
        )
    )

    class SemanticQuery:
        embedding_space = "semantic_onnx_768"

        def __call__(self, _query: str) -> list[float]:
            return vector()

    results = EventRecaller(repo, embed_func=SemanticQuery()).recall("query-without-overlap", top_k=5)

    assert HASH_BOW_RECALL_THRESHOLD == 0.50
    assert SEMANTIC_RECALL_THRESHOLD == 0.58
    assert recall_threshold_for_space("semantic_onnx_768") == SEMANTIC_RECALL_THRESHOLD
    assert [item.event_id for item in results] == ["hit"]


def test_emotional_boost_does_not_rescue_event_below_recall_threshold() -> None:
    """摘要：召回先过 hash-bow 阈值再做情绪 boost，情绪只重排不捞人。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    below_threshold = [0.45, math.sqrt(1.0 - 0.45**2), *([0.0] * (CONTENT_EMBEDDING_DIMENSIONS - 2))]
    repo.store(
        SemanticEvent(
            event_id="below",
            event_type="fact",
            subject="user",
            content="alpha-memory",
            content_embedding=below_threshold,
            emotional_valence=0.9,
            emotional_arousal=0.7,
            importance=5.0,
            created_at=time.time(),
        )
    )

    results = EventRecaller(repo, embed_func=lambda _query: vector()).recall(
        "zulu-query",
        emotional_context={"valence": 0.9, "arousal": 0.7},
        top_k=1,
    )

    assert results == []


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


def test_recall_logs_path_counts_and_fused_sources(caplog) -> None:
    """摘要：召回固定输出三路计数、RRF top-K 与来源路标记。"""
    repo = make_repo()
    recaller = EventRecaller(
        repo,
        bm25=lambda _query: ["b", "a"],
        hash_bow=lambda _query: ["a"],
        embed_func=lambda _query: vector(),
    )

    with caplog.at_level(logging.INFO, logger="offline_companion.core.memory_lifecycle.event_recaller"):
        recaller.recall("用户的技术背景", top_k=2)

    assert "semantic event recall paths query='用户的技术背景'" in caplog.text
    assert "vector=3 bm25=2 hash_bow=1 top_k=2" in caplog.text
    assert "expansion_count=0 final_ids=['a', 'b']" in caplog.text
    assert "'id': 'a'" in caplog.text
    assert "'sources': ('vector', 'bm25', 'hash_bow')" in caplog.text


def test_recall_logs_zero_counts_when_no_path_hits(caplog) -> None:
    """摘要：召回无命中时仍输出 0 计数 anchor，保留 no-hit 可见性。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    recaller = EventRecaller(repo)

    with caplog.at_level(logging.INFO, logger="offline_companion.core.memory_lifecycle.event_recaller"):
        assert recaller.recall("完全无关", top_k=2) == []

    assert "semantic event recall paths query='完全无关'" in caplog.text
    assert "vector=0 bm25=0 hash_bow=0 top_k=2 fused_top=[] expansion_count=0 final_ids=[]" in caplog.text


def test_low_importance_related_event_is_not_expanded() -> None:
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("a", "用户使用 Python", related=["low"]))
    repo.store(event("low", "临时偏好", importance=2.0))
    recaller = EventRecaller(repo, embed_func=lambda _query: vector())

    results = recaller.recall("Python", top_k=1)

    assert [item.event_id for item in results] == ["a"]


def test_related_event_must_be_active_and_only_expands_one_hop() -> None:
    """摘要：事件链只扩展 active 且重要性足够的一跳关联事件。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("a", "主事件", related=["b", "dormant"]))
    repo.store(event("b", "一跳事件", importance=4.0, related=["c"]))
    repo.store(event("c", "二跳事件", importance=4.0))
    repo.store(event("dormant", "休眠事件", importance=4.0, status="dormant"))
    recaller = EventRecaller(repo, bm25=lambda _query: ["a"])

    results = recaller.recall("主事件", top_k=1)

    assert [item.event_id for item in results] == ["a", "b"]


def test_related_event_already_in_top_events_is_not_duplicated() -> None:
    """摘要：已在 top-K 中的关联事件不重复追加或重复计数。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("a", "主事件", related=["b"], created_at=1.0))
    repo.store(event("b", "关联事件", importance=4.0, created_at=2.0))
    recaller = EventRecaller(repo, bm25=lambda _query: ["a", "b"])

    results = recaller.recall("主事件", top_k=2)

    assert [item.event_id for item in results] == ["a", "b"]
    assert repo.get("b").recall_count == 1


def test_recall_applies_decay_and_recall_boost_before_chronological_output() -> None:
    """摘要：召回选择先按 RRF×衰减排序，最终输出再按时序重组。"""
    now = time.time()
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("old", "旧高频事件", importance=5.0, recall_count=10, created_at=now - 90 * 86400))
    repo.store(event("new", "新事件", importance=5.0, created_at=now))
    repo.store(event("low", "低重要事件", importance=0.0, created_at=now + 1))
    recaller = EventRecaller(repo, bm25=lambda _query: ["old", "new", "low"])

    selected = recaller.recall("事件", top_k=2)
    only_low = EventRecaller(
        repo,
        bm25=lambda _query: ["low"],
        hash_bow=lambda _query: ["low"],
    ).recall("事件", top_k=1)

    assert [item.event_id for item in selected] == ["old", "new"]
    assert only_low[0].event_id == "low"


def test_decay_and_recall_boost_affect_top_selection() -> None:
    """摘要：衰减可让新事件升首位，召回 boost 可让旧高频事件保留竞争力。"""
    now = time.time()
    fresh_repo = EventRepository(sqlite3.connect(":memory:"))
    fresh_repo.store(event("old", "旧事件", importance=5.0, created_at=now - 90 * 86400))
    fresh_repo.store(event("new", "新事件", importance=5.0, created_at=now))
    assert EventRecaller(fresh_repo, bm25=lambda _query: ["old", "new"]).recall("事件", top_k=1)[0].event_id == "new"

    boosted_repo = EventRepository(sqlite3.connect(":memory:"))
    boosted_repo.store(event("old", "旧高频事件", importance=5.0, recall_count=10, created_at=now - 30 * 86400))
    boosted_repo.store(event("new", "新低权重事件", importance=1.0, created_at=now))
    assert EventRecaller(boosted_repo, bm25=lambda _query: ["new", "old"]).recall("事件", top_k=1)[0].event_id == "old"


def test_emotional_context_can_change_selected_event() -> None:
    """摘要：情绪上下文参与排序，匹配当前情绪的事件可升入 top-K。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("positive", "积极事件", emotional_valence=0.8, emotional_arousal=0.8))
    repo.store(event("negative", "消极事件", emotional_valence=-0.8, emotional_arousal=0.8))
    recaller = EventRecaller(repo, bm25=lambda _query: ["negative", "positive"])

    results = recaller.recall("事件", emotional_context={"valence": 0.9, "arousal": 0.8}, top_k=1)

    assert results[0].event_id == "positive"


def test_without_emotional_context_keeps_plain_rrf_order() -> None:
    """摘要：无情绪上下文时不施加情绪 boost。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("positive", "积极事件", emotional_valence=0.8, emotional_arousal=0.8))
    repo.store(event("negative", "消极事件", emotional_valence=-0.8, emotional_arousal=0.8))
    recaller = EventRecaller(repo, bm25=lambda _query: ["negative", "positive"])

    assert recaller.recall("事件", top_k=1)[0].event_id == "negative"


def test_emotional_similarity_matches_identical_context() -> None:
    assert EventRecaller._emotional_similarity({"valence": 0.2, "arousal": 0.7}, 0.2, 0.7) == 1.0
    assert EventRecaller._emotional_similarity({"valence": 0.2, "arousal": 0.7}, -1.0, 0.0) < 0.5


def test_emotional_similarity_neutral_context_is_midrange() -> None:
    """摘要：中性低唤醒事件与中性上下文保持中等相似度。"""
    assert EventRecaller._emotional_similarity({"valence": 0.0, "arousal": 0.5}, 0.0, 0.0) > 0.5


def test_recall_sorts_equal_created_at_stably_by_event_id() -> None:
    """摘要：同创建时间的结果按 event_id 稳定排序，不依赖 SQLite 返回顺序。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("b", "事件 B", created_at=100.0))
    repo.store(event("a", "事件 A", created_at=100.0))
    recaller = EventRecaller(repo, bm25=lambda _query: ["b", "a"])

    assert [item.event_id for item in recaller.recall("事件", top_k=2)] == ["a", "b"]


def test_recall_updates_last_recalled_at_for_all_returned_events() -> None:
    """摘要：召回结果中的所有事件都会更新召回时间。"""
    repo = make_repo()
    recaller = EventRecaller(repo, bm25=lambda _query: ["a"])

    before = repo.get("a").last_recalled_at
    results = recaller.recall("用户的技术背景", top_k=1)

    assert {item.event_id for item in results} == {"a", "b"}
    assert repo.get("a").last_recalled_at > before
    assert repo.get("b").last_recalled_at > 0


def test_query_expansion_falls_back_to_original_on_llm_failure() -> None:
    class BrokenLlm:
        def generate(self, _prompt: str, *, temperature: float) -> str:
            raise RuntimeError("offline")

    recaller = EventRecaller(make_repo(), llm_backend=BrokenLlm())

    assert recaller._expand_query("原始查询") == ["原始查询"]


def test_query_expansion_empty_response_uses_original_only() -> None:
    """摘要：LLM 返回空行时只保留原始查询。"""

    class EmptyLlm:
        def generate(self, _prompt: str, *, temperature: float) -> str:
            return "\n\n"

    recaller = EventRecaller(make_repo(), llm_backend=EmptyLlm())

    assert recaller._expand_query("原始查询") == ["原始查询"]


def test_query_expansion_keeps_original_and_three_variants() -> None:
    """摘要：LLM 查询扩展最多追加三个变体，并始终保留原查询。"""

    class ExpandingLlm:
        def generate(self, _prompt: str, *, temperature: float) -> str:
            assert temperature == 0.5
            return "变体一\n\n- 变体二\n* 变体三\n4. 多余变体"

    recaller = EventRecaller(make_repo(), llm_backend=ExpandingLlm())

    assert recaller._expand_query("原始查询") == ["原始查询", "变体一", "变体二", "变体三"]


def test_expanded_queries_are_sent_to_hash_bow_path() -> None:
    """摘要：hash-bow 路消费原查询与三个扩展查询。"""

    class ExpandingLlm:
        def generate(self, _prompt: str, *, temperature: float) -> str:
            return "变体一\n变体二\n变体三"

    seen_queries: list[str] = []

    def hash_bow(query: str) -> list[str]:
        seen_queries.append(query)
        return []

    EventRecaller(make_repo(), hash_bow=hash_bow, llm_backend=ExpandingLlm()).recall("原始查询")

    assert seen_queries == ["原始查询", "变体一", "变体二", "变体三"]


def test_format_event_narrative_outputs_chronological_labels_and_emotion() -> None:
    """摘要：叙事格式包含时间、类型与中文情感标签。"""
    narrative = format_event_narrative([
        event("positive", "用户完成发布", event_type="milestone", emotional_valence=0.8, emotional_arousal=0.7),
        event("negative", "用户感到低落", event_type="emotional", emotional_valence=-0.5, emotional_arousal=0.3),
        event("neutral", "用户使用 Windows", event_type="fact", emotional_valence=0.0, emotional_arousal=0.0),
    ])

    assert "[milestone] 用户完成发布（积极, 激动；情感效价 0.80，唤醒度 0.70）" in narrative
    assert "[emotional] 用户感到低落（消极, 平静；情感效价 -0.50，唤醒度 0.30）" in narrative
    assert "[fact] 用户使用 Windows（" not in narrative
    assert format_event_narrative([]) == ""


def test_persona_context_injects_recalled_semantic_event_narrative(tmp_path) -> None:
    """摘要：真链路抽样走 _assemble_context 注入语义事件叙事块。"""
    conn = connect(tmp_path / "semantic-context.db")
    new_session(conn, "session", "persona", title=None)
    repo = EventRepository(conn)
    repo.store(
        event(
            "semantic-1",
            "用户使用 Python 开发 Offline Companion",
            event_type="fact",
            importance=4.0,
            created_at=100.0,
        )
    )
    core = PersonaSessionCore(
        Persona(
            persona_id="persona",
            name="测试",
            system_prompt="基础身份",
            role_lock=True,
            memory_default_on=True,
            default_companion_display_name="助手",
            companion_display_name=None,
            raw={},
            ocean=OceanVector(0.5, 0.5, 0.5, 0.5, 0.5),
        )
    )

    _recalls, memory_block, system_prompt, _identity_reply = core._assemble_context(
        conn,
        user_message="Python 项目",
        memory_enabled=True,
    )

    assert "【相关语义事件】" in memory_block
    assert "用户使用 Python 开发 Offline Companion" in memory_block
    assert "用户使用 Python 开发 Offline Companion" not in system_prompt
