"""WebUI 消息处理与同意恢复测试。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import (
    CloudCompletionResponse,
    ModelRoutingDecision,
    PrivacyMode,
)
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.web_server import WebRuntime, create_app, process_chat_message


class _WebRouter:
    """摘要：Web 测试用固定路由器。"""

    def __init__(self, decision: ModelRoutingDecision, selected_type: str) -> None:
        self._decision = decision
        self._selected_type = selected_type

    def route(self, _query: str, *, privacy_mode: PrivacyMode) -> ModelRoutingDecision:
        return self._decision

    def model_type(self, _name: str) -> str | None:
        return self._selected_type


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
    assert out["reply"]
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


def test_web_app_consent_roundtrip(tmp_path) -> None:
    rt = _runtime(tmp_path)
    rt.orchestrator.consent_gateway = UIHostConsentGateway()
    rt.orchestrator.privacy_mode = PrivacyMode.ALWAYS_ASK
    rt.orchestrator.model_router = _WebRouter(
        ModelRoutingDecision(
            selected_model="deepseek-v4",
            fallback_model="qwen2.5-1.5b-instruct-q4_k_m",
            requires_consent=True,
            reason="cloud_candidate_selected",
            estimated_input_tokens=120,
            estimated_output_tokens=240,
            estimated_cost=0.02,
        ),
        selected_type="cloud",
    )
    rt.orchestrator.cloud_post = lambda _req: CloudCompletionResponse(text="Web 云端回复", raw={})

    app = create_app(rt)
    client = app.test_client()

    pending = client.post("/api/chat", json={"message": "请联网查询一下"}).get_json()
    assert pending["requires_consent"] is True
    request_id = pending["consent_request_id"]
    assert request_id

    modal = client.get("/api/consent").get_json()
    assert modal["request_id"] == request_id
    assert modal["status"] == "pending"

    resumed = client.post("/api/consent", json={"request_id": request_id, "allowed": True})
    assert resumed.status_code == 200
    payload = resumed.get_json()
    assert "Web 云端回复" in payload["reply"]
    assert payload["route_mode"] == "cloud"
