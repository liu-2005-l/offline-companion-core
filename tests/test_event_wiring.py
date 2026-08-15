"""Phase 2.5 核心模块事件接线测试。"""

from pathlib import Path

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.plan_orchestrator import ConsentRequest
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import PurposeType
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator


def _event_stream() -> EventStream:
    """创建测试用事件流。"""
    return EventStream("session-1", build_default_registry())


def test_conversation_turn_writes_session_and_model_events_with_one_trace_id(tmp_path) -> None:
    conn = connect(tmp_path / "events.db")
    persona = load_persona_file(Path(__file__).resolve().parents[1] / "configs/personas/default.yaml")
    new_session(conn, "session-1", persona.persona_id, title=None)
    stream = _event_stream()
    orchestrator = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("event-wiring"),
        conn=conn,
        session_id="session-1",
        triggers=load_triggers(),
        event_stream=stream,
    )

    result = orchestrator.run_turn("你好", memory_on=False)

    assert result.reply
    events = stream.get_events()
    assert [event.event_type for event in events] == [
        "session/turn_start",
        "session/message",
        "model/switched",
        "session/message",
        "session/turn_end",
    ]
    trace_ids = {event.payload.get("trace_id") for event in events}
    assert len(trace_ids) == 1
    assert None not in trace_ids
    assert events[1].payload["role"] == "user"
    assert events[3].payload["role"] == "assistant"


def test_consent_writes_asked_and_decided_pair() -> None:
    stream = _event_stream()
    gateway = UIHostConsentGateway(event_stream=stream)
    request = ConsentRequest(
        plan_id="plan-1",
        step_id="step-1",
        skill_id="skill_cloud_x",
        operation="route_cloud_turn",
        purpose_type=PurposeType.CLOUD_ROUTING,
        metadata={"trace_id": "trace-1"},
    )

    assert gateway.submit(request) is False
    request_id = str(gateway.last_artifact["request_id"])
    gateway.decide(request_id, allowed=True)

    events = stream.get_events()
    assert [event.event_type for event in events] == ["consent/asked", "consent/decided"]
    assert all(event.payload["trace_id"] == "trace-1" for event in events)
    assert events[1].payload["allowed"] is True
