"""摘要：知识检索与个人记忆隔离（Sprint 4.3）。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from dataclasses import replace

from offline_companion.core.knowledge_rag.config import load_knowledge_config
from offline_companion.core.knowledge_rag.ingest import ingest_jsonl_file
from offline_companion.core.memory_lifecycle.drafts import count_memory_chunks
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.runtime.storage_index.knowledge_store import connect_knowledge
from offline_companion.shell.ui_host.knowledge_turn import run_knowledge_search


def test_search_knowledge_does_not_write_memory_chunks(tmp_path) -> None:
    companion = connect(tmp_path / "companion.db")
    new_session(companion, "s1", "default", title=None)
    MemoryLifecycleManager.add_memory_chunk(companion, "已有记忆", session_id="s1", source="seed")
    before = count_memory_chunks(companion)

    kdb = Path(tempfile.mkdtemp()) / "knowledge.db"
    kconn = connect_knowledge(kdb)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    ingest_jsonl_file(kconn, sample)

    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    core = PersonaSessionCore(persona)
    cfg = replace(load_knowledge_config(), enabled=True, db_path=kdb, answer_after_search=False)

    result = run_knowledge_search(
        query="压力",
        config=cfg,
        knowledge_conn=kconn,
        companion_conn=companion,
        session_id="s1",
        persona=persona,
        session_core=core,
        backend=EchoBackend("k"),
        memory_on=True,
    )
    assert result.hits
    assert "来源:" in result.snippet_display or "fixture://" in result.snippet_display
    assert count_memory_chunks(companion) == before


def test_search_knowledge_answer_mode_still_no_memory_from_hits(tmp_path) -> None:
    """answer_after_search 会落库对话消息，但不得因检索命中新增 memory_chunks。"""
    companion = connect(tmp_path / "c2.db")
    new_session(companion, "s1", "default", title=None)
    before = count_memory_chunks(companion)

    kdb = Path(tempfile.mkdtemp()) / "knowledge.db"
    kconn = connect_knowledge(kdb)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    ingest_jsonl_file(kconn, sample)

    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    core = PersonaSessionCore(persona)
    cfg = replace(load_knowledge_config(), enabled=True, db_path=kdb, answer_after_search=True)

    run_knowledge_search(
        query="压力",
        config=cfg,
        knowledge_conn=kconn,
        companion_conn=companion,
        session_id="s1",
        persona=persona,
        session_core=core,
        backend=EchoBackend("k"),
        memory_on=False,
    )
    assert count_memory_chunks(companion) == before
