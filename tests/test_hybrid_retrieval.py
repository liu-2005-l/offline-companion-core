"""双源融合检索（P3-A）测试。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.knowledge_rag.hybrid import hybrid_retrieve
from offline_companion.core.knowledge_rag.ingest import ingest_jsonl_file
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.runtime.storage_index.knowledge_store import connect_knowledge


def test_hybrid_retrieve_returns_knowledge_and_memory_hits(tmp_path) -> None:
    knowledge_conn = connect_knowledge(tmp_path / "knowledge.db")
    companion_conn = connect(tmp_path / "companion.db")
    new_session(companion_conn, "s1", "default", title=None)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    ingest_jsonl_file(knowledge_conn, sample)
    MemoryLifecycleManager.add_memory_chunk(companion_conn, "我对压力很敏感", session_id="s1", source="test")

    result = hybrid_retrieve(
        query="压力",
        knowledge_conn=knowledge_conn,
        companion_conn=companion_conn,
        knowledge_limit=5,
        memory_limit=5,
        final_limit=5,
    )

    assert result.hits
    assert result.citations
    assert any(hit.source_type == "knowledge" for hit in result.hits)
    assert any(hit.source_type == "memory" for hit in result.hits)
    assert result.display_text.startswith("【融合检索结果】")


def test_hybrid_retrieve_dedupes_identical_content_across_sources(tmp_path) -> None:
    knowledge_conn = connect_knowledge(tmp_path / "knowledge.db")
    companion_conn = connect(tmp_path / "companion.db")
    new_session(companion_conn, "s1", "default", title=None)

    knowledge_conn.execute(
        "INSERT INTO knowledge_documents(title, source_uri, license_note, ingested_at) VALUES(?,?,?,?);",
        ("重复文档", "fixture://dup", None, 0.0),
    )
    doc_id = int(knowledge_conn.execute("SELECT id FROM knowledge_documents LIMIT 1;").fetchone()["id"])
    knowledge_conn.execute(
        "INSERT INTO knowledge_chunks(doc_id, body, meta_json) VALUES(?,?,?);",
        (doc_id, "完全重复的文本片段", "{}"),
    )
    MemoryLifecycleManager.add_memory_chunk(
        companion_conn,
        "完全重复的文本片段",
        session_id="s1",
        source="test",
    )

    result = hybrid_retrieve(
        query="完全重复",
        knowledge_conn=knowledge_conn,
        companion_conn=companion_conn,
        knowledge_limit=5,
        memory_limit=5,
        final_limit=5,
    )

    matching = [hit for hit in result.hits if hit.snippet == "完全重复的文本片段"]
    assert len(matching) == 1
    assert len(result.citations) == len(result.hits)


def test_hybrid_retrieve_citations_are_sequential(tmp_path) -> None:
    knowledge_conn = connect_knowledge(tmp_path / "knowledge.db")
    companion_conn = connect(tmp_path / "companion.db")
    new_session(companion_conn, "s1", "default", title=None)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    ingest_jsonl_file(knowledge_conn, sample)

    result = hybrid_retrieve(
        query="压力",
        knowledge_conn=knowledge_conn,
        companion_conn=companion_conn,
        knowledge_limit=5,
        memory_limit=5,
        final_limit=3,
    )

    assert [citation.index for citation in result.citations] == list(range(1, len(result.citations) + 1))


def test_hybrid_retrieve_includes_semantic_knowledge_path(tmp_path) -> None:
    knowledge_conn = connect_knowledge(tmp_path / "knowledge.db")
    companion_conn = connect(tmp_path / "companion.db")
    new_session(companion_conn, "s1", "default", title=None)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    ingest_jsonl_file(knowledge_conn, sample)

    result = hybrid_retrieve(
        query="压力很大怎么办",
        knowledge_conn=knowledge_conn,
        companion_conn=companion_conn,
        knowledge_limit=5,
        memory_limit=2,
        final_limit=5,
    )

    assert result.hits
    assert any(hit.metadata.get("retriever") == "knowledge_semantic" for hit in result.hits)
