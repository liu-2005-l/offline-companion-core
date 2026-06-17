"""桌面壳内嵌 HTTP API（Flask test client）。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session, recent_messages
from offline_companion.shell.ui_host.bootstrap import ECHO_NO_MODEL_LABEL
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shared.types import PrivacyMode


def _runtime(tmp_path) -> DesktopRuntime:
    conn = connect(tmp_path / "http.db")
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    new_session(conn, "h1", persona.persona_id, title=None)
    orch = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("desktop"),
        conn=conn,
        session_id="h1",
        triggers=load_triggers(),
    )
    return DesktopRuntime(
        orchestrator=orch,
        memory_on=True,
        session_id="h1",
        persona_name="助手一号",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        model_label=ECHO_NO_MODEL_LABEL,
    )


def test_desktop_http_chat_and_clear(tmp_path) -> None:
    rt = _runtime(tmp_path)
    app = create_desktop_app(rt)
    client = app.test_client()

    r = client.post("/api/chat", json={"message": "你好"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["reply"]
    assert not data["blocked"]

    assert len(recent_messages(rt.orchestrator.conn, "h1", limit=10)) >= 2

    r2 = client.post("/api/clear", json={})
    assert r2.status_code == 200
    assert r2.get_json()["ok"] is True
    assert recent_messages(rt.orchestrator.conn, "h1", limit=10) == []

    r3 = client.post("/api/chat", json={"message": "我不想活了"})
    data3 = r3.get_json()
    assert data3["blocked"]
    assert data3["safety_tier"] == SafetyTier.CRISIS_SELF.value
