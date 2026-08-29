from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from offline_companion.core.emotion_analyzer.context import EmotionContext
from offline_companion.core.memory_lifecycle.event_recaller import EventRecaller
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import CONTENT_EMBEDDING_DIMENSIONS, SemanticEvent
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.deterministic_embedding import embed_text
from offline_companion.shared.types import OceanVector, Persona
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator


F1_CONTENT = "用户的猫名叫布丁，三岁，喜欢玩逗猫棒"
F1_QUERY = "布丁最近还玩逗猫棒吗"
F2_CONTENT = "狸奴常追羽杆嬉戏，午后卧在窗边晒太阳"
F2_QUERY = "猫咪爱玩哪种玩具"


class CaptureBackend:
    """摘要：记录 LLM 请求中的 prompt 与记忆块，供注入层断言。"""

    def __init__(self) -> None:
        self.system_prompts: list[str] = []
        self.memory_blocks: list[str] = []

    def generate(self, *, system_prompt, history, user_message, memory_block, max_tokens=256):  # type: ignore[no-untyped-def]
        self.system_prompts.append(str(system_prompt))
        self.memory_blocks.append(str(memory_block))
        return "ok"

    def generate_stream(self, **_kwargs):  # type: ignore[no-untyped-def]
        yield "ok"


def _persona() -> Persona:
    """摘要：构造启用记忆的最小测试人格。"""
    return Persona(
        persona_id="phase65",
        name="phase65",
        system_prompt="基础身份",
        role_lock=True,
        memory_default_on=True,
        default_companion_display_name="助手",
        companion_display_name=None,
        raw={},
        ocean=OceanVector(0.5, 0.5, 0.5, 0.5, 0.5),
    )


def _session_core() -> PersonaSessionCore:
    """摘要：构造固定 hash-bow 入口的会话核心，保持 6.5 词面 fixture 口径。"""
    return PersonaSessionCore(
        _persona(),
        semantic_embed_func=lambda text: embed_text(text, dimensions=CONTENT_EMBEDDING_DIMENSIONS),
    )


def _conn(tmp_path: Path, name: str = "phase65.db") -> sqlite3.Connection:
    """摘要：创建带 session 的测试连接。"""
    conn = connect(tmp_path / name)
    new_session(conn, "s1", "phase65", title=None)
    return conn


def _event(
    event_id: str,
    content: str,
    *,
    embedding: list[float] | None = None,
    importance: float = 0.6,
    created_at: float | None = None,
    emotional_valence: float = 0.0,
    emotional_arousal: float = 0.0,
) -> SemanticEvent:
    """摘要：构造 6.5 注入层测试事件。"""
    return SemanticEvent(
        event_id=event_id,
        event_type="fact",
        subject="user",
        content=content,
        content_embedding=embed_text(content, dimensions=CONTENT_EMBEDDING_DIMENSIONS)
        if embedding is None
        else embedding,
        emotional_valence=emotional_valence,
        emotional_arousal=emotional_arousal,
        importance=importance,
        created_at=time.time() if created_at is None else created_at,
    )


def test_assemble_context_injects_lexical_semantic_event_fixture_f1(tmp_path: Path) -> None:
    """摘要：U15 的 F1 词面命中事件会进入 LLM 记忆块。"""
    conn = _conn(tmp_path)
    repo = EventRepository(conn)
    repo.store(_event("E-F1-1", F1_CONTENT))

    _recalls, memory_block, _system_prompt, _identity_reply = _session_core()._assemble_context(
        conn,
        user_message=F1_QUERY,
        memory_enabled=True,
    )

    assert "【相关语义事件】" in memory_block
    assert "布丁" in memory_block
    assert repo.get("E-F1-1").recall_count == 1


def test_assemble_context_does_not_inject_lexically_missed_fixture_f2(tmp_path: Path) -> None:
    """摘要：U16 主形态使用词面错开对，semantic 实测 0.373039 也低于 0.58。"""
    assert EventRecaller._tokenize(F1_QUERY) & EventRecaller._tokenize(F1_CONTENT)
    assert EventRecaller._tokenize(F2_QUERY) & EventRecaller._tokenize(F2_CONTENT) == set()
    conn = _conn(tmp_path)
    repo = EventRepository(conn)
    repo.store(_event("E-F2-1", F2_CONTENT))

    _recalls, memory_block, _system_prompt, _identity_reply = _session_core()._assemble_context(
        conn,
        user_message=F2_QUERY,
        memory_enabled=True,
    )

    assert "【相关语义事件】" not in memory_block
    assert repo.get("E-F2-1").recall_count == 0


def test_assemble_context_keeps_empty_store_without_semantic_event_block(tmp_path: Path) -> None:
    """摘要：U16 附带 sanity 锁住空库不会产生任意注入块。"""
    conn = _conn(tmp_path)

    _recalls, memory_block, _system_prompt, _identity_reply = _session_core()._assemble_context(
        conn,
        user_message=F1_QUERY,
        memory_enabled=True,
    )

    assert "【相关语义事件】" not in memory_block


def test_assemble_context_passes_emotional_context_to_semantic_recaller(tmp_path: Path) -> None:
    """摘要：U18 锁住 SessionCore 到 EventRecaller 的情绪 boost 接线。"""
    conn = _conn(tmp_path)
    repo = EventRepository(conn)
    query = "近期安排怎么样"
    query_embedding = embed_text(query, dimensions=CONTENT_EMBEDDING_DIMENSIONS)
    for index in range(5):
        repo.store(_event(f"neutral-{index}", f"普通占位事件 {index}", embedding=query_embedding, created_at=float(index)))
    repo.store(
        _event(
            "E-F3-1",
            "用户每周六早上跑步五公里",
            embedding=query_embedding,
            created_at=10.0,
            emotional_valence=0.8,
            emotional_arousal=0.7,
        )
    )

    no_emotion_block = _session_core()._assemble_context(
        conn,
        user_message=query,
        memory_enabled=True,
    )[1]
    emotion_block = _session_core()._assemble_context(
        conn,
        user_message=query,
        memory_enabled=True,
        emotion_context=EmotionContext(emotion="joy", valence=0.9, arousal=0.7),
    )[1]

    assert "五公里" not in no_emotion_block
    assert "五公里" in emotion_block


def test_orchestrator_turn_passes_f1_memory_block_to_backend(tmp_path: Path) -> None:
    """摘要：T19 复用 F1，端到端捕获 LLM 请求中的记忆块。"""
    conn = _conn(tmp_path)
    EventRepository(conn).store(_event("E-F1-1", F1_CONTENT))
    backend = CaptureBackend()
    orchestrator = ConversationOrchestrator(
        session_core=_session_core(),
        backend=backend,
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )

    result = orchestrator.run_turn(F1_QUERY, memory_on=True)

    assert result.reply == "ok"
    assert backend.memory_blocks
    assert "【相关语义事件】" in backend.memory_blocks[-1]
    assert "布丁" in backend.memory_blocks[-1]


def test_orchestrator_turn_uses_profile_display_name_in_backend_system_prompt(tmp_path: Path) -> None:
    """摘要：T20 捕获 LLM 请求，确认画像自称进入 system_prompt。"""
    conn = _conn(tmp_path)
    MemoryLifecycleManager.add_memory_chunk(
        conn,
        "助手自画像：名字 = 小诺",
        session_id="s1",
        source="semantic_auto",
        meta={
            "memory_type": "agent_profile",
            "target": "assistant",
            "field": "display_name",
            "value": "小诺",
        },
    )
    backend = CaptureBackend()
    orchestrator = ConversationOrchestrator(
        session_core=_session_core(),
        backend=backend,
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )

    orchestrator.run_turn("你好", memory_on=True)

    assert backend.system_prompts
    assert "【当前自称】小诺" in backend.system_prompts[-1]
    assert "【当前自称】助手" not in backend.system_prompts[-1]
