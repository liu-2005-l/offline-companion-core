"""Plugin iframe 安全隔离测试。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import AppPaths, PrivacyMode
from offline_companion.shell.ui_host.bootstrap import ECHO_NO_MODEL_LABEL
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime


def _runtime(tmp_path) -> DesktopRuntime:
    conn = connect(tmp_path / "plugin-security.db")
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    new_session(conn, "p1", persona.persona_id, title=None)
    orchestrator = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("plugin"),
        conn=conn,
        session_id="p1",
        triggers=load_triggers(),
    )
    return DesktopRuntime(
        orchestrator=orchestrator,
        memory_on=True,
        session_id="p1",
        persona_name="test-assistant",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        model_label=ECHO_NO_MODEL_LABEL,
        triggers=load_triggers(),
        paths=AppPaths(
            root=tmp_path,
            db_path=tmp_path / "plugin-security.db",
            personas_dir=tmp_path / "personas",
            exports_dir=tmp_path / "exports",
        ),
    )


def test_plugin_memory_read_allowed(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    MemoryLifecycleManager.add_memory_chunk(
        runtime.orchestrator.conn,
        "seed memory",
        session_id=runtime.session_id,
        source="seed",
    )
    client = create_desktop_app(runtime).test_client()
    session = client.post("/api/plugins/session", json={"plugin_id": "memory-inspector"}).get_json()
    response = client.post(
        "/api/plugins/message",
        json={
            "type": "plugin.bridge.request",
            "plugin_id": "memory-inspector",
            "session_id": session["session_id"],
            "session_token": session["session_token"],
            "request_id": "req-1",
            "capability": "memory.read",
            "payload": {"limit": 5},
        },
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["items"]


def test_plugin_rejects_unauthorized_capability(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()
    session = client.post("/api/plugins/session", json={"plugin_id": "unsafe-skill"}).get_json()
    response = client.post(
        "/api/plugins/message",
        json={
            "type": "plugin.bridge.request",
            "plugin_id": "unsafe-skill",
            "session_id": session["session_id"],
            "session_token": session["session_token"],
            "request_id": "req-2",
            "capability": "skill.call",
            "payload": {"name": "agent-toolbox", "payload": {"command": "whoami"}},
        },
    )
    payload = response.get_json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert "Capability is not granted" in payload["error"]


def test_plugin_rejects_invalid_schema_payload(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()
    session = client.post("/api/plugins/session", json={"plugin_id": "bad-schema"}).get_json()
    response = client.post(
        "/api/plugins/message",
        json={
            "type": "plugin.bridge.request",
            "plugin_id": "bad-schema",
            "session_id": session["session_id"],
            "session_token": session["session_token"],
            "request_id": "req-3",
            "capability": "memory.toggle",
            "payload": {"enabled": "no"},
        },
    )
    payload = response.get_json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert "must be a boolean" in payload["error"]


def test_plugin_rejects_destroyed_session(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()
    session = client.post("/api/plugins/session", json={"plugin_id": "memory-toggle"}).get_json()
    client.post(f"/api/plugins/session/{session['session_id']}/destroy", json={})
    response = client.post(
        "/api/plugins/message",
        json={
            "type": "plugin.bridge.request",
            "plugin_id": "memory-toggle",
            "session_id": session["session_id"],
            "session_token": session["session_token"],
            "request_id": "req-4",
            "capability": "memory.toggle",
            "payload": {"enabled": False},
        },
    )
    payload = response.get_json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert "has been destroyed" in payload["error"]


def test_plugin_session_payload_keeps_opaque_origin_safe_baseline(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()
    session = client.post("/api/plugins/session", json={"plugin_id": "memory-toggle"}).get_json()
    assert session["sandbox"] == "allow-scripts"
    assert "allow-same-origin" not in session["sandbox"]


def test_plugin_rejects_invalid_session_token(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()
    session = client.post("/api/plugins/session", json={"plugin_id": "memory-toggle"}).get_json()
    response = client.post(
        "/api/plugins/message",
        json={
            "type": "plugin.bridge.request",
            "plugin_id": "memory-toggle",
            "session_id": session["session_id"],
            "session_token": "forged-token",
            "request_id": "req-5",
            "capability": "memory.toggle",
            "payload": {"enabled": False},
        },
    )
    payload = response.get_json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert "session_token validation failed" in payload["error"]
