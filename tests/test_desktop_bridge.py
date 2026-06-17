"""桌面 bridge 逻辑（不启动 pywebview 窗口）。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.bootstrap import ECHO_NO_MODEL_LABEL
from offline_companion.shell.ui_host.desktop.bridge import DesktopBridge
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shared.types import PrivacyMode


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
    assert data["purpose_type"] == "skill_cloud_call"
