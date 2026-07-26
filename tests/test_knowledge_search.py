"""知识检索与语义召回测试。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.knowledge_rag.config import load_knowledge_config
from offline_companion.core.knowledge_rag.format import format_knowledge_snippets
from offline_companion.core.knowledge_rag.ingest import ingest_jsonl_file
from offline_companion.core.knowledge_rag.search import search_knowledge, search_knowledge_semantic
from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.runtime.storage_index.knowledge_store import connect_knowledge


def test_knowledge_ingest_and_search(tmp_path) -> None:
    db = tmp_path / "knowledge.db"
    conn = connect_knowledge(db)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    n = ingest_jsonl_file(conn, sample)
    assert n >= 2
    hits = search_knowledge(conn, "压力", limit=5, session_id="t1")
    assert hits
    assert any("压力" in h.body for h in hits)
    display = format_knowledge_snippets(hits)
    assert "来源:" in display
    assert "fixture://" in display


def test_knowledge_semantic_search_returns_related_hits(tmp_path) -> None:
    db = tmp_path / "knowledge.db"
    conn = connect_knowledge(db)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    ingest_jsonl_file(conn, sample)

    hits = search_knowledge_semantic(conn, "压力很大怎么办", limit=5, session_id="t2")

    assert hits
    assert any("压力" in h.body for h in hits)


def test_knowledge_chunks_store_embeddings_after_ingest(tmp_path) -> None:
    db = tmp_path / "knowledge.db"
    conn = connect_knowledge(db)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    ingest_jsonl_file(conn, sample)

    row = conn.execute(
        "SELECT embedding_blob, embedding_model, embedding_dim FROM knowledge_chunks ORDER BY id LIMIT 1;"
    ).fetchone()

    assert row is not None
    assert row["embedding_blob"] is not None
    assert row["embedding_model"] == "deterministic_hash_bow_v1"
    assert int(row["embedding_dim"]) == 128


def test_knowledge_config_default_off() -> None:
    cfg = load_knowledge_config()
    assert cfg.enabled is False
    assert cfg.answer_after_search is False


def test_knowledge_query_still_passes_safety_for_remember_phrase() -> None:
    r = classify_user_text("请记住我喜欢简短回答")
    assert r.tier is SafetyTier.OK
