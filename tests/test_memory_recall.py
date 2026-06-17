from __future__ import annotations

import sqlite3

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.recall import format_recall_prompt_block, recall
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import Persona
from pathlib import Path


def test_recall_matched_on_non_empty(tmp_path) -> None:
    conn = connect(tmp_path / "r.db")
    new_session(conn, "s1", "default", title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "My cat is called Mimi", session_id="s1", source="test")
    hits = recall(conn, "Mimi", limit=5)
    assert hits
    assert hits[0].matched_on.get("summary")
    assert "decay_factor" in hits[0].matched_on


def test_recall_keyword_overlap_cilantro_and_food(tmp_path) -> None:
    conn = connect(tmp_path / "food.db")
    new_session(conn, "s1", "default", title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "我讨厌香菜", session_id="s1", source="test")
    hits = recall(conn, "今天想吃点菜，有什么建议吗", limit=5)
    assert hits
    bodies = " ".join(h.body for h in hits)
    assert "香菜" in bodies
    assert any("菜" in str(h.matched_on.get("matched_keywords", [])) or "菜" in h.matched_on.get("summary", "") for h in hits)


def test_recall_time_decay_prefers_newer_when_keyword_tie(tmp_path) -> None:
    conn = connect(tmp_path / "decay.db")
    new_session(conn, "s1", "default", title=None)
    import time

    old_t = time.time() - 60.0 * 86400.0
    new_t = time.time() - 1.0 * 86400.0
    conn.execute(
        "INSERT INTO memory_chunks(session_id, source, body, created_at, updated_at, meta_json) "
        "VALUES(?,?,?,?,?,?);",
        ("s1", "test", "我喜欢吃苹果", old_t, old_t, "{}"),
    )
    conn.execute(
        "INSERT INTO memory_chunks(session_id, source, body, created_at, updated_at, meta_json) "
        "VALUES(?,?,?,?,?,?);",
        ("s1", "test", "我也喜欢苹果派", new_t, new_t, "{}"),
    )
    # 同步 FTS（触发器应已写入；若无则手动）
    for row in conn.execute("SELECT id, body FROM memory_chunks;").fetchall():
        try:
            conn.execute("INSERT INTO memory_fts(rowid, body) VALUES(?,?);", (row["id"], row["body"]))
        except sqlite3.IntegrityError:
            pass

    hits = recall(conn, "苹果", limit=2, half_life_sec=30 * 86400)
    assert len(hits) >= 1
    if len(hits) >= 2:
        assert hits[0].decay_factor >= hits[1].decay_factor


def test_assemble_reply_skips_memory_when_disabled(tmp_path) -> None:
    persona = Persona(
        persona_id="t",
        name="t",
        system_prompt="You are helpful.",
        role_lock=True,
        memory_default_on=False,
        default_companion_display_name="助手一号",
        companion_display_name=None,
        raw={},
    )
    core = PersonaSessionCore(persona)
    conn = connect(tmp_path / "asm.db")
    new_session(conn, "s1", "t", title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "我讨厌香菜", session_id="s1", source="test")
    backend = EchoBackend("test")
    result = core.assemble_reply(
        backend,
        conn,
        user_message="点菜",
        history=[],
        memory_enabled=False,
        max_tokens=64,
    )
    assert result.memory_recalls == []
    assert result.memory_block == ""
    assert "香菜" not in result.reply


def test_format_recall_block_contains_preference_constraint(tmp_path) -> None:
    conn = connect(tmp_path / "taboo.db")
    new_session(conn, "s1", "default", title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "我讨厌香菜", session_id="s1", source="test")
    hits = recall(conn, "今天想吃点菜", limit=5)
    assert hits
    block = format_recall_prompt_block(hits)
    assert "不得推荐" in block
    assert "替代方案" in block
    assert "【禁忌】" in block
    assert "香菜" in block


def test_format_recall_block_contains_answer_directive(tmp_path) -> None:
    conn = connect(tmp_path / "name.db")
    new_session(conn, "s1", "default", title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "我叫Master", session_id="s1", source="test")
    hits = recall(conn, "我叫什么", limit=5)
    assert hits
    block = format_recall_prompt_block(hits)
    assert "【回答要求】" in block
    assert "不要重复对话历史中无关寒暄" in block


def test_format_recall_block_always_appends_constraint_for_neutral_memory(tmp_path) -> None:
    conn = connect(tmp_path / "neutral.db")
    new_session(conn, "s1", "default", title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "我的猫叫咪咪", session_id="s1", source="test")
    hits = recall(conn, "咪咪", limit=5)
    assert hits
    block = format_recall_prompt_block(hits)
    assert "重要提醒" in block
    assert "替代方案" in block
    assert "【禁忌】" not in block


def test_default_persona_chinese_no_fixed_nickname() -> None:
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    assert persona.default_companion_display_name == "助手一号"
    assert persona.companion_display_name is None
    assert "陪伴" in persona.system_prompt
    assert "小伴" not in persona.system_prompt
    assert "online assistant" not in persona.system_prompt.lower()


def test_companion_display_name_override() -> None:
    from offline_companion.core.persona_session.persona_loader import (
        apply_companion_display_name,
        resolved_companion_display_name,
    )

    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    assert resolved_companion_display_name(persona) == "助手一号"
    custom = apply_companion_display_name(persona, "阿青")
    assert resolved_companion_display_name(custom) == "阿青"
    core = PersonaSessionCore(custom)
    assert "【当前自称】阿青" in core.system_prompt_locked


def test_assemble_reply_injects_memory_when_enabled(tmp_path) -> None:
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    core = PersonaSessionCore(persona)
    conn = connect(tmp_path / "asm2.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "我讨厌香菜", session_id="s1", source="test")
    backend = EchoBackend("test")
    result = core.assemble_reply(
        backend,
        conn,
        user_message="今天想吃点菜",
        history=[],
        memory_enabled=True,
        max_tokens=64,
    )
    assert result.memory_recalls
    assert "香菜" in result.memory_block or any("香菜" in h.body for h in result.memory_recalls)
    assert "重要提醒" in result.memory_block
    assert "[memory]" in result.reply or "菜" in result.reply
