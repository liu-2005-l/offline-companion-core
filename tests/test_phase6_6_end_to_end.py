from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from offline_companion.core.memory_lifecycle.event_extractor import EventExtractor
from offline_companion.core.memory_lifecycle.event_recaller import EventRecaller
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import CONTENT_EMBEDDING_DIMENSIONS, SemanticEvent
from offline_companion.core.memory_lifecycle.idle_hook import MemoryIdleHook
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session, recent_messages
from offline_companion.shared.deterministic_embedding import embed_text
from offline_companion.shared.types import OceanVector, Persona
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator


class Phase66Backend:
    """摘要：同时充当聊天后端与语义提取后端的确定性测试替身。"""

    def __init__(self, extraction_responses: list[str] | None = None) -> None:
        self.extraction_responses = list(extraction_responses or [])
        self.memory_blocks: list[str] = []
        self.system_prompts: list[str] = []

    def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if args and kwargs.get("temperature") == 0.3:
            return self.extraction_responses.pop(0) if self.extraction_responses else "[]"
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        self.memory_blocks.append(str(kwargs.get("memory_block") or ""))
        return "ok"

    def generate_stream(self, **_kwargs):  # type: ignore[no-untyped-def]
        yield "ok"


class FailingExtractionBackend(Phase66Backend):
    """摘要：提取调用失败但普通聊天仍成功。"""

    def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if args and kwargs.get("temperature") == 0.3:
            raise RuntimeError("extract timeout")
        return super().generate(*args, **kwargs)


class BrokenRepo:
    """摘要：模拟召回/GC 阶段 SQLite 不可用。"""

    def get_active(self, limit: int = 1000):  # type: ignore[no-untyped-def]
        raise sqlite3.OperationalError("database is locked")

    def mark_dormant(self, _event_id: str) -> None:
        raise sqlite3.OperationalError("database is locked")


class SessionWindow:
    """摘要：按 bootstrap 逻辑提供 idle 残余提取窗口。"""

    def __init__(self, conn: sqlite3.Connection, session_id: str, extractor: EventExtractor) -> None:
        self._conn = conn
        self._session_id = session_id
        self._extractor = extractor

    def get_pending_extraction(self):
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE session_id = ? AND role = 'user'",
            (self._session_id,),
        ).fetchone()
        current_turn = int(row["count"]) if row is not None else 0
        last_turn = self._extractor.last_extracted_turn
        if current_turn <= last_turn:
            return None
        messages = recent_messages(self._conn, self._session_id, limit=20)
        return (
            self._session_id,
            [{"role": item.role, "content": item.content} for item in messages],
            (max(1, last_turn + 1), current_turn),
        )


def _persona() -> Persona:
    """摘要：构造启用记忆的 Phase 6.6 测试人格。"""
    return Persona(
        persona_id="phase66",
        name="phase66",
        system_prompt="基础身份",
        role_lock=True,
        memory_default_on=True,
        default_companion_display_name="助手",
        companion_display_name=None,
        raw={},
        ocean=OceanVector(0.5, 0.5, 0.5, 0.5, 0.5),
    )


def _event(
    event_id: str,
    content: str,
    *,
    importance: float = 3.0,
    created_at: float | None = None,
    related: list[str] | None = None,
    valence: float = 0.0,
    arousal: float = 0.0,
) -> SemanticEvent:
    """摘要：构造带生产 hash-bow 向量的语义事件。"""
    return SemanticEvent(
        event_id=event_id,
        event_type="fact",
        subject="user",
        content=content,
        content_embedding=embed_text(content, dimensions=CONTENT_EMBEDDING_DIMENSIONS),
        emotional_valence=valence,
        emotional_arousal=arousal,
        importance=importance,
        related_events=related or [],
        created_at=time.time() if created_at is None else created_at,
    )


def _orchestrator(tmp_path: Path, backend: Phase66Backend) -> ConversationOrchestrator:
    """摘要：构造带真实 EventExtractor 的本地会话编排器。"""
    conn = connect(tmp_path / "phase66.db")
    persona = _persona()
    new_session(conn, "s1", persona.persona_id, title=None)
    repo = EventRepository(conn)
    orchestrator = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=backend,
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
        event_extractor=EventExtractor(repo, backend, lambda text: embed_text(text, dimensions=768)),
    )
    return orchestrator


def _run_turns(orchestrator: ConversationOrchestrator, count: int) -> None:
    """摘要：连续运行指定轮数的普通本地对话。"""
    for index in range(count):
        orchestrator.run_turn(f"第 {index + 1} 轮稳定事实", memory_on=True)


def test_phase66_periodic_extraction_runs_at_turn_ten_only(tmp_path: Path) -> None:
    """摘要：W1/W3 锁住第 10 轮触发、第 9 轮不触发。"""
    backend = Phase66Backend([
        '[{"event_type":"fact","subject":"user","content":"用户决定采用本地优先","importance":3}]'
    ])
    orchestrator = _orchestrator(tmp_path, backend)

    _run_turns(orchestrator, 9)
    assert EventRepository(orchestrator.conn).get_active() == []

    orchestrator.run_turn("第 10 轮稳定事实", memory_on=True)

    events = EventRepository(orchestrator.conn).get_active()
    assert len(events) == 1
    assert events[0].temporal_marker == "session:s1:turn:1-10"
    assert orchestrator.event_extractor.last_extracted_turn == 10


def test_phase66_pure_chitchat_extraction_stores_no_events(tmp_path: Path) -> None:
    """摘要：W2 纯寒暄到周期边界时提取返回空，DB 不新增。"""
    backend = Phase66Backend(["[]"])
    orchestrator = _orchestrator(tmp_path, backend)

    _run_turns(orchestrator, 10)

    assert EventRepository(orchestrator.conn).get_active() == []
    assert orchestrator.event_extractor.last_extracted_turn == 10


def test_phase66_two_periodic_windows_store_two_batches(tmp_path: Path) -> None:
    """摘要：W4 第 10 与第 20 轮各自形成独立提取窗口。"""
    backend = Phase66Backend([
        '[{"event_type":"fact","subject":"user","content":"AlphaZephyr","importance":3}]',
        '[{"event_type":"fact","subject":"user","content":"BetaQuasar","importance":3}]',
    ])
    orchestrator = _orchestrator(tmp_path, backend)

    _run_turns(orchestrator, 20)

    events = sorted(EventRepository(orchestrator.conn).get_active(), key=lambda item: item.temporal_marker)
    assert [event.content for event in events] == ["AlphaZephyr", "BetaQuasar"]
    assert [event.temporal_marker for event in events] == ["session:s1:turn:1-10", "session:s1:turn:11-20"]


def test_phase66_idle_extracts_initial_and_post_boundary_residual_windows(tmp_path: Path) -> None:
    """摘要：W5/W6 消费游标三律，idle 只补未被周期提取覆盖的残余窗口。"""
    backend = Phase66Backend([
        '[{"event_type":"fact","subject":"user","content":"GammaOrbit","importance":3}]',
        '[{"event_type":"fact","subject":"user","content":"DeltaHarbor","importance":3}]',
    ])
    orchestrator = _orchestrator(tmp_path, backend)
    extractor = orchestrator.event_extractor
    assert extractor is not None
    _run_turns(orchestrator, 17)

    hook = MemoryIdleHook(extractor, EventRepository(orchestrator.conn), SessionWindow(orchestrator.conn, "s1", extractor))
    actions = hook.on_idle(300)

    events = sorted(EventRepository(orchestrator.conn).get_active(), key=lambda item: item.temporal_marker)
    assert actions == ["extracted 1 events from residual turns"]
    assert [event.temporal_marker for event in events] == ["session:s1:turn:1-10", "session:s1:turn:11-17"]
    assert hook.on_idle(300) == []


def test_phase66_cross_session_recall_hit_and_miss_follow_hash_bow_scope(tmp_path: Path) -> None:
    """摘要：W7/W8 跨 session 召回跟随 F1/F2 词面口径。"""
    conn = connect(tmp_path / "cross-session.db")
    persona = _persona()
    new_session(conn, "session-a", persona.persona_id, title=None)
    repo = EventRepository(conn)
    repo.store(_event("f1", "用户记录 ProjectZephyr tokenalpha"))
    new_session(conn, "session-b", persona.persona_id, title=None)
    core = PersonaSessionCore(persona)

    hit_block = core._assemble_context(conn, user_message="ProjectZephyr tokenalpha", memory_enabled=True)[1]
    miss_block = core._assemble_context(conn, user_message="weather forecast unrelated", memory_enabled=True)[1]

    assert "ProjectZephyr" in hit_block
    assert "【相关语义事件】" not in miss_block


def test_phase66_recalled_events_are_injected_chronologically(tmp_path: Path) -> None:
    """摘要：W9 多个召回事件最终叙事按时间顺序排列。"""
    conn = connect(tmp_path / "chronological.db")
    new_session(conn, "s1", "phase66", title=None)
    repo = EventRepository(conn)
    repo.store(_event("new", "用户喜欢布丁的新逗猫棒", created_at=200.0))
    repo.store(_event("old", "用户的猫布丁喜欢逗猫棒", created_at=100.0))

    block = PersonaSessionCore(_persona())._assemble_context(
        conn,
        user_message="布丁 逗猫棒",
        memory_enabled=True,
    )[1]

    assert block.index("用户的猫布丁喜欢逗猫棒") < block.index("用户喜欢布丁的新逗猫棒")


def test_phase66_explicit_related_event_one_hop_is_injected(tmp_path: Path) -> None:
    """摘要：W10 只承诺显式 related_events 一跳扩展，不承诺 0.70 语义 related。"""
    conn = connect(tmp_path / "related.db")
    new_session(conn, "s1", "phase66", title=None)
    repo = EventRepository(conn)
    repo.store(_event("primary", "用户的猫布丁喜欢逗猫棒", related=["linked"]))
    repo.store(_event("linked", "布丁需要定期剪指甲", importance=4.0))

    block = PersonaSessionCore(_persona())._assemble_context(
        conn,
        user_message="布丁 逗猫棒",
        memory_enabled=True,
    )[1]

    assert "用户的猫布丁喜欢逗猫棒" in block
    assert "布丁需要定期剪指甲" in block


def test_phase66_recall_db_failure_returns_empty() -> None:
    """摘要：T24 召回 DB 不可用时返回空列表，不阻断对话。"""
    assert EventRecaller(BrokenRepo()).recall("任意查询") == []  # type: ignore[arg-type]


def test_phase66_idle_gc_db_lock_skips_current_round(tmp_path: Path) -> None:
    """摘要：T25 IdleThink GC 遇到 DB 锁时跳过本轮，等待下次重试。"""
    backend = Phase66Backend()
    extractor = EventExtractor(EventRepository(sqlite3.connect(":memory:")), backend, lambda text: embed_text(text, dimensions=768))
    hook = MemoryIdleHook(extractor, BrokenRepo(), session_repo=None)  # type: ignore[arg-type]

    assert hook.on_idle(300) == []


def test_phase66_extraction_timeout_does_not_break_turn(tmp_path: Path) -> None:
    """摘要：T21 提取阶段超时不影响当前对话完成。"""
    orchestrator = _orchestrator(tmp_path, FailingExtractionBackend())

    _run_turns(orchestrator, 10)

    assert EventRepository(orchestrator.conn).get_active() == []
