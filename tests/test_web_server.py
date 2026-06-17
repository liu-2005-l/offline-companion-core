"""WebUI 消息处理（不依赖 Flask 运行时）。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.web_server import WebRuntime, process_chat_message


def _runtime(tmp_path) -> WebRuntime:
    conn = connect(tmp_path / "web.db")
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    new_session(conn, "web1", persona.persona_id, title=None)
    orch = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("web"),
        conn=conn,
        session_id="web1",
        triggers=load_triggers(),
    )
    return WebRuntime(orchestrator=orch, memory_on=True, session_id="web1")


def test_process_chat_empty_message(tmp_path) -> None:
    rt = _runtime(tmp_path)
    out = process_chat_message(rt, "   ")
    assert out["reply"] == "（请输入内容）"
    assert not out["blocked"]


def test_process_chat_safety_block(tmp_path) -> None:
    rt = _runtime(tmp_path)
    out = process_chat_message(rt, "我不想活了")
    assert out["blocked"]
    assert out["safety_tier"] == SafetyTier.CRISIS_SELF.value
    assert out["reply"]


def test_process_chat_remember_and_recall(tmp_path) -> None:
    rt = _runtime(tmp_path)
    save = process_chat_message(rt, "#remember 我讨厌香菜")
    assert save["memory_saved"]
    out = process_chat_message(rt, "晚上点菜吃什么")
    assert not out["blocked"]
    assert out["memory_recall_count"] >= 1
