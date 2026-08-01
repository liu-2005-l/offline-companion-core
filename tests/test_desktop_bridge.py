"""桌面 bridge 逻辑（不启动 pywebview 窗口）。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import (
    AppPaths,
    CloudCompletionResponse,
    ModelRoutingDecision,
    PrivacyMode,
)
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.ui_host.bootstrap import ECHO_NO_MODEL_LABEL
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.bridge import DesktopBridge
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime


class _BridgeRouter:
    def __init__(self, decision: ModelRoutingDecision, selected_type: str) -> None:
        self._decision = decision
        self._selected_type = selected_type

    def route(self, _query: str, *, privacy_mode: PrivacyMode) -> ModelRoutingDecision:
        return self._decision

    def model_type(self, _name: str) -> str | None:
        return self._selected_type


def _bridge(tmp_path) -> DesktopBridge:
    conn = connect(tmp_path / "desktop.db")
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    new_session(conn, "d1", persona.persona_id, title=None)
    orch = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("desktop"),
        conn=conn,
        session_id="d1",
        triggers=load_triggers(),
    )
    runtime = DesktopRuntime(
        orchestrator=orch,
        memory_on=True,
        session_id="d1",
        persona_name="助手一号",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        model_label=ECHO_NO_MODEL_LABEL,
        triggers=load_triggers(),
        paths=AppPaths(
            root=tmp_path,
            db_path=tmp_path / "desktop.db",
            personas_dir=tmp_path / "personas",
            exports_dir=tmp_path / "exports",
        ),
    )
    return DesktopBridge(runtime)


def test_bridge_status(tmp_path) -> None:
    br = _bridge(tmp_path)
    st = br.get_status()
    assert st["memory_on"] is True
    assert st["session_id"] == "d1"
    assert st["privacy_mode"] == PrivacyMode.LOCAL_ONLY.value
    assert st["model_label"] == ECHO_NO_MODEL_LABEL


def test_bridge_run_turn_safety(tmp_path) -> None:
    br = _bridge(tmp_path)
    out = br.run_turn("我不想活了")
    assert out["blocked"]
    assert out["safety_tier"] == SafetyTier.CRISIS_SELF.value


def test_bridge_memory_toggle(tmp_path) -> None:
    br = _bridge(tmp_path)
    br.set_memory(False)
    assert br.get_status()["memory_on"] is False


def test_bridge_consent_placeholder(tmp_path) -> None:
    br = _bridge(tmp_path)
    data = br.consent_placeholder()
    assert "title" in data
    assert data["purpose_type"] == "skill_cloud_inference"


def test_bridge_consent_decision_resumes_pending_turn(tmp_path) -> None:
    br = _bridge(tmp_path)
    gateway = UIHostConsentGateway()
    br._runtime.orchestrator.consent_gateway = gateway
    br._runtime.orchestrator.privacy_mode = PrivacyMode.ALWAYS_ASK
    br._runtime.orchestrator.model_router = _BridgeRouter(
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
    br._runtime.orchestrator.cloud_post = lambda _req: CloudCompletionResponse(text="云端已恢复", raw={})

    pending = br.run_turn("请联网查询一下")
    assert pending["requires_consent"] is True
    request_id = pending["consent_request_id"]
    assert request_id

    resumed = br.consent_decision(request_id, True)
    assert "云端已恢复" in resumed["reply"]
    assert resumed["route_mode"] == "cloud"
