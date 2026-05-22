"""摘要：记忆摘要草稿（Sprint 4.2）。"""

from __future__ import annotations

from offline_companion.core.memory_lifecycle.drafts import (
    build_extractive_summary,
    confirm_draft,
    count_memory_chunks,
    create_draft_from_session,
    discard_draft,
    list_pending_drafts,
)
from offline_companion.runtime.storage_index.engine import append_message, connect, new_session
from offline_companion.shared.types import MessageRow


def test_extractive_summary_includes_entities() -> None:
    msgs = [
        MessageRow(role="user", content="#remember 我讨厌香菜", created_at=1.0, meta={}),
        MessageRow(role="assistant", content="好的，我会记住。", created_at=2.0, meta={}),
        MessageRow(role="user", content="晚上想点菜", created_at=3.0, meta={}),
    ]
    body = build_extractive_summary(msgs)
    assert "摘要草稿" in body
    assert "香菜" in body or "讨厌" in body


def test_draft_confirm_workflow(tmp_path) -> None:
    conn = connect(tmp_path / "d.db")
    new_session(conn, "s1", "default", title=None)
    append_message(conn, "s1", "user", "#remember 我喜欢简短回答", meta={})
    append_message(conn, "s1", "assistant", "收到。", meta={})
    assert count_memory_chunks(conn) == 0
    draft = create_draft_from_session(conn, "s1")
    assert draft.status == "pending"
    assert count_memory_chunks(conn) == 0
    pending = list_pending_drafts(conn, "s1")
    assert len(pending) == 1
    mid = confirm_draft(conn, draft.id)
    assert mid is not None
    assert count_memory_chunks(conn) == 1
    assert not list_pending_drafts(conn, "s1")


def test_draft_discard_no_memory_write(tmp_path) -> None:
    conn = connect(tmp_path / "d2.db")
    new_session(conn, "s1", "default", title=None)
    append_message(conn, "s1", "user", "今天很累", meta={})
    draft = create_draft_from_session(conn, "s1")
    assert discard_draft(conn, draft.id)
    assert count_memory_chunks(conn) == 0
