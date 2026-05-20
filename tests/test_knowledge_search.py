"""摘要：知识 RAG 插件（Sprint 3）。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.knowledge_rag.config import load_knowledge_config
from offline_companion.core.knowledge_rag.format import format_knowledge_snippets
from offline_companion.core.knowledge_rag.ingest import ingest_jsonl_file
from offline_companion.core.knowledge_rag.search import search_knowledge
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


def test_knowledge_config_default_off() -> None:
    cfg = load_knowledge_config()
    assert cfg.enabled is False
    assert cfg.answer_after_search is False


def test_knowledge_query_still_passes_safety_for_remember_phrase() -> None:
    r = classify_user_text("请记住我喜欢简短回答")
    assert r.tier is SafetyTier.OK
