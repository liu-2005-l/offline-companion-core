"""ConversationOrchestrator 单轮编排测试。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.emotion_analyzer import EmotionClassifier
from offline_companion.core.local_reformatter.rule_reformatter import LOCAL_FALLBACK_PREFIX
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.errors import CloudConnectorError
from offline_companion.shared.types import CloudCompletionRequest, CloudCompletionResponse
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator


def _orch(tmp_path, db_name: str = "o.db") -> tuple[ConversationOrchestrator, object]:
    conn = connect(tmp_path / db_name)
    persona = load_persona_file(Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml")
    new_session(conn, "s1", persona.persona_id, title=None)
    orchestrator = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("test"),
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )
    return orchestrator, conn


def test_orchestrator_safety_block(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    result = orchestrator.run_turn("我不想活了", memory_on=True)
    assert result.blocked_by_safety
    assert result.safety_tier == SafetyTier.CRISIS_SELF.value
    row = conn.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT 1;").fetchone()
    assert row["role"] == "assistant"


def test_orchestrator_remember_and_chat(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    first = orchestrator.run_turn("#remember 我讨厌香菜", memory_on=True)
    assert first.memory_saved
    assert first.memory_only
    second = orchestrator.run_turn("晚上想点菜", memory_on=True)
    assert second.reply
    assert second.memory_recalls
    hits = MemoryLifecycleManager.recall(conn, "点菜", limit=3)
    assert hits


def test_orchestrator_cloud_degrade_prefix(tmp_path) -> None:
    orchestrator, _conn = _orch(tmp_path, "cloud.db")

    def fail(_req: CloudCompletionRequest) -> CloudCompletionResponse:
        raise CloudConnectorError("stub fail")

    result = orchestrator.run_cloud_turn("帮我写一句问候", purpose="test", memory_on=False, cloud_post=fail)
    assert result.cloud_degraded
    assert result.reply.startswith(LOCAL_FALLBACK_PREFIX)


def test_orchestrator_memory_off_no_recall_in_turn(tmp_path) -> None:
    orchestrator, _conn = _orch(tmp_path)
    orchestrator.run_turn("#remember 测试", memory_on=True)
    result = orchestrator.run_turn("测试", memory_on=False)
    assert result.reply
    assert not result.memory_recalls


def test_orchestrator_persists_emotion_column(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    result = orchestrator.run_turn("我现在很焦虑，有点睡不着", memory_on=False)
    assert result.reply
    row = conn.execute(
        "SELECT role, emotion FROM messages WHERE role = 'user' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row is not None
    assert row["emotion"] == "anxiety"


def test_orchestrator_b0_failure_does_not_block_main_path(tmp_path, monkeypatch) -> None:
    orchestrator, conn = _orch(tmp_path)

    def fail(self, text: str):
        raise RuntimeError("b0 boom")

    monkeypatch.setattr(EmotionClassifier, "predict", fail)
    result = orchestrator.run_turn("今天天气不错", memory_on=False)
    assert result.reply
    row = conn.execute(
        "SELECT role, emotion FROM messages WHERE role = 'user' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row is not None
    assert row["emotion"] is None


def test_orchestrator_emotion_strategy_flows_to_reply(tmp_path) -> None:
    orchestrator, _conn = _orch(tmp_path)
    result = orchestrator.run_turn("我现在真的很难过", memory_on=False)
    assert result.reply
    assert "我会陪着你" in result.reply


def test_orchestrator_local_reply_runs_through_b4(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    result = orchestrator.run_turn("我现在真的很难过！！", memory_on=False)
    assert result.reply
    assert "我会陪着你" in result.reply
    row = conn.execute(
        "SELECT role, meta_json FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row is not None
    assert "reformatted" in row["meta_json"]
