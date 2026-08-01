"""桌面壳内嵌 HTTP API（Flask test client）。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session, recent_messages
from offline_companion.shared.types import (
    AppPaths,
    CloudCompletionResponse,
    ModelRoutingDecision,
    PrivacyMode,
)
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.ui_host.bootstrap import ECHO_NO_MODEL_LABEL
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime


class _HttpRouter:
    def __init__(self, decision: ModelRoutingDecision, selected_type: str) -> None:
        self._decision = decision
        self._selected_type = selected_type

    def route(self, _query: str, *, privacy_mode: PrivacyMode) -> ModelRoutingDecision:
        return self._decision

    def model_type(self, _name: str) -> str | None:
        return self._selected_type


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
        triggers=load_triggers(),
        paths=AppPaths(
            root=tmp_path,
            db_path=tmp_path / "http.db",
            personas_dir=tmp_path / "personas",
            exports_dir=tmp_path / "exports",
        ),
    )


def test_desktop_http_release_metadata(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.content_type in {"image/vnd.microsoft.icon", "image/x-icon"}

    about = client.get("/api/about")
    assert about.status_code == 200
    payload = about.get_json()
    assert payload["app_version"] == "1.0.0"
    assert payload["model_label"] == ECHO_NO_MODEL_LABEL

    missing = client.get("/missing")
    assert missing.status_code == 404
    assert missing.get_json() == {"error": "not_found"}


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


def test_desktop_http_consent_roundtrip(tmp_path) -> None:
    rt = _runtime(tmp_path)
    rt.orchestrator.consent_gateway = UIHostConsentGateway()
    rt.orchestrator.privacy_mode = PrivacyMode.ALWAYS_ASK
    rt.orchestrator.model_router = _HttpRouter(
        ModelRoutingDecision(
            selected_model="deepseek-v4",
            fallback_model="qwen2.5-1.5b-instruct-q4_k_m",
            requires_consent=True,
            reason="cloud_candidate_selected",
            estimated_input_tokens=100,
            estimated_output_tokens=200,
            estimated_cost=0.02,
        ),
        selected_type="cloud",
    )
    rt.orchestrator.cloud_post = lambda _req: CloudCompletionResponse(text="云端已批准", raw={})

    app = create_desktop_app(rt)
    client = app.test_client()

    pending = client.post("/api/chat", json={"message": "请联网查询一下"}).get_json()
    assert pending["requires_consent"] is True
    request_id = pending["consent_request_id"]

    modal = client.get("/api/consent").get_json()
    assert modal["request_id"] == request_id
    assert modal["status"] == "pending"

    resumed = client.post("/api/consent", json={"request_id": request_id, "allowed": True})
    assert resumed.status_code == 200
    payload = resumed.get_json()
    assert "云端已批准" in payload["reply"]
    assert payload["route_mode"] == "cloud"
