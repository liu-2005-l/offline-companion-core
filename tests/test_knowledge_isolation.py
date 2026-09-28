"""摘要：知识检索与个人记忆隔离（Sprint 4.3）。"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

import offline_companion.shell.ui_host.knowledge_turn as knowledge_turn_module
from offline_companion.core.knowledge_rag.config import load_knowledge_config
from offline_companion.core.knowledge_rag.ingest import ingest_jsonl_file
from offline_companion.core.memory_lifecycle.drafts import count_memory_chunks
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.persona_constraint import load_persona_constraint_assets
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


def test_knowledge_answer_fail_close_is_error_row_without_reformat(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要：知识回答消费面在格式化和 completed 落库前识别 fail-close。"""
    companion = connect(tmp_path / "knowledge-fail-close.db")
    new_session(companion, "s1", "default", title=None)
    kdb = tmp_path / "knowledge.db"
    kconn = connect_knowledge(kdb)
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_sample" / "sample.jsonl"
    ingest_jsonl_file(kconn, sample)
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    cfg = replace(load_knowledge_config(), enabled=True, db_path=kdb, answer_after_search=True)
    expected_reply = load_persona_constraint_assets().source_payloads["reply_copy"][
        "l4_fail_close_copy"
    ]

    class FailClosedCore:
        def assemble_reply(self, *args, **kwargs):
            del args, kwargs
            return type(
                "Result",
                (),
                {
                    "reply": expected_reply,
                    "fail_closed": True,
                    "error_code": "persona_l4_fail_closed",
                },
            )()

    def reject_reformat(*_args, **_kwargs):
        raise AssertionError("fail-close 文案不得进入 reformatter")

    monkeypatch.setattr(knowledge_turn_module, "reformat_cloud_reply", reject_reformat)
    result = run_knowledge_search(
        query="压力",
        config=cfg,
        knowledge_conn=kconn,
        companion_conn=companion,
        session_id="s1",
        persona=persona,
        session_core=FailClosedCore(),
        backend=EchoBackend("k"),
        memory_on=False,
    )
    assistant = companion.execute(
        "SELECT content, status, meta_json FROM messages "
        "WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
    ).fetchone()

    assert result.error_code == "persona_l4_fail_closed"
    assert result.reply == expected_reply
    assert assistant["content"] == expected_reply
    assert assistant["status"] == "error"
    assert '"l4_fail_closed": true' in assistant["meta_json"]
