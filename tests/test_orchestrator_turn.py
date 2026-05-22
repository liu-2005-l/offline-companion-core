"""摘要：ConversationOrchestrator 单轮编排（Sprint 1）。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator


def _orch(tmp_path, db_name: str = "o.db") -> tuple[ConversationOrchestrator, object]:
    conn = connect(tmp_path / db_name)
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    new_session(conn, "s1", persona.persona_id, title=None)
    orch = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("test"),
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )
    return orch, conn


def test_orchestrator_safety_block(tmp_path) -> None:
    orch, conn = _orch(tmp_path)
    result = orch.run_turn("我不想活了", memory_on=True)
    assert result.blocked_by_safety
    assert result.safety_tier == SafetyTier.CRISIS_SELF.value
    row = conn.execute(
        "SELECT role, content FROM messages ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row["role"] == "assistant"


def test_orchestrator_remember_and_chat(tmp_path) -> None:
    orch, conn = _orch(tmp_path)
    r1 = orch.run_turn("#remember 我讨厌香菜", memory_on=True)
    assert r1.memory_saved
    assert r1.memory_only
    r2 = orch.run_turn("晚上想点菜", memory_on=True)
    assert r2.reply
    assert r2.memory_recalls
    hits = MemoryLifecycleManager.recall(conn, "点菜", limit=3)
    assert hits


def test_orchestrator_cloud_degrade_prefix(tmp_path) -> None:
    """云端失败时使用本地硬降级前缀，不回传云端原文。"""
    from offline_companion.core.local_reformatter.rule_reformatter import LOCAL_FALLBACK_PREFIX
    from offline_companion.shared.errors import CloudConnectorError
    from offline_companion.shared.types import CloudCompletionRequest, CloudCompletionResponse

    orch, _conn = _orch(tmp_path, "cloud.db")

    def _fail(_req: CloudCompletionRequest) -> CloudCompletionResponse:
        raise CloudConnectorError("stub fail")

    r = orch.run_cloud_turn(
        "帮我写一句问候",
        purpose="test",
        memory_on=False,
        cloud_post=_fail,
    )
    assert r.cloud_degraded
    assert r.reply.startswith(LOCAL_FALLBACK_PREFIX)


def test_orchestrator_memory_off_no_recall_in_turn(tmp_path) -> None:
    orch, _conn = _orch(tmp_path)
    orch.run_turn("#remember 测试", memory_on=True)
    r = orch.run_turn("测试", memory_on=False)
    assert r.reply
    assert not r.memory_recalls
