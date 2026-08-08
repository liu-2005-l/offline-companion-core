"""桌面壳内嵌 HTTP API（Flask test client）。"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

import offline_companion
import offline_companion.shell.ui_host.desktop.http_host as desktop_http
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import (
    append_message,
    connect,
    new_session,
    recent_messages,
)
from offline_companion.shared.errors import OutboundDenied
from offline_companion.shared.types import (
    AppPaths,
    CloudCompletionResponse,
    ModelDescriptor,
    ModelRoutingDecision,
    PrivacyMode,
)
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.ui_host.bootstrap import ECHO_NO_MODEL_LABEL
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.http_host import _json_safe, create_desktop_app
from offline_companion.shell.ui_host.desktop.privacy_socket_guard import (
    disable_privacy_socket_guard,
    is_socket_guard_enabled,
)
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime


class _HttpRouter:
    def __init__(self, decision: ModelRoutingDecision, selected_type: str) -> None:
        self._decision = decision
        self._selected_type = selected_type

    def route(self, _query: str, *, privacy_mode: PrivacyMode) -> ModelRoutingDecision:
        return self._decision

    def model_type(self, _name: str) -> str | None:
        return self._selected_type


class _SplitStreamBackend(EchoBackend):
    def generate_stream(self, **_kwargs):
        yield "A"
        yield "B"


def _sse_payloads(text: str) -> list[dict]:
    items: list[dict] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            items.append(json.loads(line[5:].strip()))
    return items


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

    api_script = client.get("/shell_api.js")
    assert api_script.status_code == 200
    assert "async function sendMessage" in api_script.text

    sse = client.get("/api/sse-test")
    assert sse.status_code == 200
    assert sse.content_type.startswith("text/event-stream")
    assert sse.headers["Cache-Control"] == "no-cache"
    assert sse.headers["X-Accel-Buffering"] == "no"
    assert sse.headers["Connection"] == "keep-alive"
    assert 'data: {"i": 0}' in sse.text
    assert 'data: {"done": true}' in sse.text

    about = client.get("/api/about")
    assert about.status_code == 200
    payload = about.get_json()
    assert payload["app_version"] == offline_companion.__version__
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
    assert data["user_message_id"]
    assert data["message_id"]

    assert len(recent_messages(rt.orchestrator.conn, "h1", limit=10)) >= 2

    r2 = client.post("/api/clear", json={})
    assert r2.status_code == 200
    assert r2.get_json()["ok"] is True
    assert recent_messages(rt.orchestrator.conn, "h1", limit=10) == []

    r3 = client.post("/api/chat", json={"message": "我不想活了"})
    data3 = r3.get_json()
    assert data3["blocked"]
    assert data3["safety_tier"] == SafetyTier.CRISIS_SELF.value


def test_desktop_http_chat_stream_returns_sse_events(tmp_path) -> None:
    rt = _runtime(tmp_path)
    rt.orchestrator.backend = _SplitStreamBackend("split")
    client = create_desktop_app(rt).test_client()

    response = client.post("/api/chat", json={"message": "ping", "stream": True})

    assert response.status_code == 200
    assert response.content_type.startswith("text/event-stream")
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert response.headers["Connection"] == "keep-alive"
    events = _sse_payloads(response.text)
    assert events[0] == {"recall": 0}
    assert [event["token"] for event in events if "token" in event] == ["A", "B"]
    assert events[-1]["done"] is True
    assert events[-1]["reply"] == "AB"
    assert events[-1]["message_id"]
    assert events[-1]["memory_recall_count"] == 0
    assert len(recent_messages(rt.orchestrator.conn, "h1", limit=10)) >= 2


def test_desktop_http_chat_stream_safety_returns_single_done(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    response = client.post("/api/chat", json={"message": "我不想活了", "stream": True})

    events = _sse_payloads(response.text)
    assert len(events) == 1
    assert events[0]["done"] is True
    assert events[0]["blocked"] is True
    assert events[0]["safety_tier"] == SafetyTier.CRISIS_SELF.value

def test_desktop_http_json_safe_preserves_nested_payload() -> None:
    payload = {"items": [{"meta": {"tags": ("a", "b")}}]}

    assert _json_safe(payload) == {"items": [{"meta": {"tags": ["a", "b"]}}]}


def test_desktop_http_sessions_and_messages(tmp_path) -> None:
    rt = _runtime(tmp_path)
    append_message(rt.orchestrator.conn, "h1", "user", "你好", {"quote_msg_id": 1})
    append_message(rt.orchestrator.conn, "h1", "assistant", "你好呀", {"source": "mock"})
    client = create_desktop_app(rt).test_client()

    sessions = client.get("/api/sessions")
    assert sessions.status_code == 200
    sessions_payload = sessions.get_json()
    assert sessions_payload["total"] == 1
    session_item = sessions_payload["items"][0]
    assert session_item["session_id"] == "h1"
    assert session_item["message_count"] == 2
    assert session_item["current"] is True

    messages = client.get("/api/sessions/h1/messages")
    assert messages.status_code == 200
    messages_payload = messages.get_json()
    assert messages_payload["total"] == 2
    assert messages_payload["items"][0]["msg_idx"] == 0
    assert messages_payload["items"][0]["role"] == "user"
    assert messages_payload["items"][0]["meta"]["quote_msg_id"] == 1
    assert messages_payload["items"][1]["msg_idx"] == 1


def test_desktop_http_manual_memory_create_and_patch(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    created = client.post(
        "/api/memories",
        json={"content": "用户喜欢雨天散步", "source": "manual", "msg_id": 7, "tags": ["preference"]},
    )
    assert created.status_code == 201
    item = created.get_json()["item"]
    assert item["body"] == "用户喜欢雨天散步"
    assert item["source"] == "manual"
    assert item["status"] == "active"
    assert item["metadata"]["msg_id"] == 7

    patched = client.patch(
        f"/api/memories/{item['id']}",
        json={"content": "用户喜欢小雨天散步", "status": "inactive"},
    )
    assert patched.status_code == 200
    patched_item = patched.get_json()["item"]
    assert patched_item["body"] == "用户喜欢小雨天散步"
    assert patched_item["status"] == "invalid"

    restored = client.patch(f"/api/memories/{item['id']}", json={"status": "active"})
    assert restored.status_code == 200
    assert restored.get_json()["item"]["status"] == "active"


def test_desktop_http_plan_decompose_and_execute(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    created = client.post("/api/plan/decompose", json={"goal": "实现一个本地验证脚本"})
    assert created.status_code == 201
    plan = created.get_json()["plan"]
    assert plan["id"].startswith("plan_")
    assert plan["steps"][0]["status"] == "pending"

    executed = client.post(f"/api/plan/{plan['id']}/execute", json={"step_id": 0, "timeout": 20})
    assert executed.status_code == 200
    payload = executed.get_json()
    assert payload["step"]["status"] == "done"
    assert payload["step"]["result"].startswith("步骤已完成")


def test_desktop_http_plan_requires_consent_and_resume(tmp_path) -> None:
    rt = _runtime(tmp_path)
    rt.orchestrator.consent_gateway = UIHostConsentGateway(db_conn=rt.orchestrator.conn)
    client = create_desktop_app(rt).test_client()

    plan = client.post("/api/plan/decompose", json={"goal": "部署服务并配置网络权限"}).get_json()["plan"]
    high_risk = next(step for step in plan["steps"] if step["requires_auth"])

    pending = client.post(f"/api/plan/{plan['id']}/execute", json={"step_id": high_risk["id"], "timeout": 20})
    assert pending.status_code == 409
    pending_payload = pending.get_json()
    assert pending_payload["error"] == "requires_consent"
    assert pending_payload["status"] == "requires_consent"
    assert pending_payload["consent_request_id"]
    assert pending_payload["consent_payload"]["request_id"] == pending_payload["consent_request_id"]
    assert pending_payload["step"]["status"] == "consent"

    consent = client.post(
        "/api/consent",
        json={"request_id": pending_payload["consent_request_id"], "allowed": True},
    )
    assert consent.status_code == 200
    assert consent.get_json()["artifact"]["user_decision"] == "allow"

    resumed = client.post(
        f"/api/plan/{plan['id']}/execute",
        json={
            "step_id": high_risk["id"],
            "timeout": 20,
            "consent_request_id": pending_payload["consent_request_id"],
        },
    )
    assert resumed.status_code == 200
    assert resumed.get_json()["step"]["status"] == "done"
    row = rt.orchestrator.conn.execute("SELECT COUNT(*) AS c FROM consent_artifacts;").fetchone()
    assert row["c"] >= 1


def test_desktop_http_plan_consent_reject_keeps_plan_paused(tmp_path) -> None:
    rt = _runtime(tmp_path)
    rt.orchestrator.consent_gateway = UIHostConsentGateway(db_conn=rt.orchestrator.conn)
    client = create_desktop_app(rt).test_client()

    plan = client.post("/api/plan/decompose", json={"goal": "部署服务并配置网络权限"}).get_json()["plan"]
    high_risk = next(step for step in plan["steps"] if step["requires_auth"])
    pending_payload = client.post(
        f"/api/plan/{plan['id']}/execute",
        json={"step_id": high_risk["id"], "timeout": 20},
    ).get_json()
    request_id = pending_payload["consent_request_id"]

    rejected = client.post("/api/consent", json={"request_id": request_id, "allowed": False})

    assert rejected.status_code == 200
    assert rejected.get_json()["artifact"]["user_decision"] == "deny"
    assert rejected.get_json()["artifact"]["allowed"] is False
    pending = rt.orchestrator.consent_gateway.pending[request_id]
    assert pending.decided is True
    assert pending.allowed is False

    denied_execute = client.post(
        f"/api/plan/{plan['id']}/execute",
        json={"step_id": high_risk["id"], "timeout": 20, "consent_request_id": request_id},
    )
    assert denied_execute.status_code == 403
    assert denied_execute.get_json()["error"] == "consent_not_allowed"
    restored_plan = rt.orchestrator.conn.execute(
        "SELECT status FROM plans WHERE plan_id = ?;",
        (plan["id"],),
    ).fetchone()
    assert restored_plan["status"] == "paused"
    row = rt.orchestrator.conn.execute("SELECT COUNT(*) AS c FROM consent_artifacts;").fetchone()
    assert row["c"] >= 1
    artifact_row = rt.orchestrator.conn.execute(
        "SELECT artifact_json FROM consent_artifacts WHERE request_id = ?;",
        (request_id,),
    ).fetchone()
    assert json.loads(artifact_row["artifact_json"])["allowed"] is False


def test_desktop_http_plan_execute_timeout(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    plan = client.post("/api/plan/decompose", json={"goal": "分析记忆字段"}).get_json()["plan"]
    timed_out = client.post(f"/api/plan/{plan['id']}/execute", json={"step_id": 0, "timeout": 0})

    assert timed_out.status_code == 408
    payload = timed_out.get_json()
    assert payload["error"] == "timeout"
    assert payload["status"] == "timeout"
    assert payload["step"]["status"] == "failed"


def test_desktop_http_personas_list_and_activate(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    listed = client.get("/api/personas")
    assert listed.status_code == 200
    items = listed.get_json()["items"]
    assert len(items) >= 3
    assert {"id", "name", "avatar", "desc", "ocean", "traits", "anchor", "active"} <= set(items[0])
    assert sum(1 for item in items if item["active"]) == 1

    target = items[-1]
    activated = client.post(f"/api/personas/{target['id']}/activate")
    assert activated.status_code == 200
    assert activated.get_json()["persona"]["active"] is True

    status = client.get("/api/status").get_json()
    assert status["persona_id"] == target["id"]
    active_count = rt.orchestrator.conn.execute("SELECT COUNT(*) AS c FROM personas WHERE active = 1;").fetchone()
    assert int(active_count["c"]) == 1


def test_desktop_http_persona_activation_survives_app_recreate(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()
    items = client.get("/api/personas").get_json()["items"]
    target = next(item for item in items if item["id"] != rt.orchestrator.session_core.persona.persona_id)

    activated = client.post(f"/api/personas/{target['id']}/activate")
    recreated = create_desktop_app(rt).test_client()
    status = recreated.get("/api/status").get_json()
    personas = recreated.get("/api/personas").get_json()["items"]

    assert activated.status_code == 200
    assert status["persona_id"] == target["id"]
    assert sum(1 for item in personas if item["active"]) == 1
    assert next(item for item in personas if item["id"] == target["id"])["active"] is True


def test_desktop_http_models_list_activate_and_auto(tmp_path, monkeypatch) -> None:
    rt = _runtime(tmp_path)
    model_path = tmp_path / "models" / "demo-model.gguf"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"gguf")
    local_model = ModelDescriptor(
        model_id="demo-model",
        display_name="Demo Model",
        gguf_path=str(model_path),
        source="test",
        status="ready",
        backend="llama_cpp",
        n_ctx=512,
    )
    monkeypatch.setattr(desktop_http, "discover_models", lambda *, data_root_override=None: [local_model])
    monkeypatch.setattr(desktop_http, "_load_local_model_backend", lambda runtime, model: EchoBackend("demo-model"))
    client = create_desktop_app(rt).test_client()

    listed = client.get("/api/models")
    assert listed.status_code == 200
    payload = listed.get_json()
    assert "items" in payload
    assert "auto" in payload

    model_id = payload["items"][0]["id"]
    activated = client.post(f"/api/models/{model_id}/activate", json={"enabled": True, "name": "demo-model"})
    assert activated.status_code == 200
    assert activated.get_json()["active_model_id"] == model_id

    auto = client.post("/api/models/auto", json={"enabled": True})
    assert auto.status_code == 200
    assert auto.get_json()["auto"] is True


def test_desktop_http_cloud_models_locked_until_login(tmp_path, monkeypatch) -> None:
    rt = _runtime(tmp_path)
    cloud = ModelDescriptor(
        model_id="cloud-demo",
        display_name="Cloud Demo",
        gguf_path=None,
        source="test",
        status="ready",
        backend="cloud",
    )
    monkeypatch.setattr(desktop_http, "discover_models", lambda *, data_root_override=None: [cloud])
    client = create_desktop_app(rt).test_client()

    listed = client.get("/api/models").get_json()["items"]
    assert listed[0]["type"] == "cloud"
    assert listed[0]["locked"] is True

    client.get("/api/auth/status")
    token = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))["token"]
    login = client.post("/api/auth/login", json={"token": token})
    assert login.status_code == 200

    unlocked = client.get("/api/models").get_json()["items"]
    assert unlocked[0]["locked"] is False


def test_desktop_http_model_activate_reloads_local_backend(tmp_path, monkeypatch) -> None:
    rt = _runtime(tmp_path)
    model_path = tmp_path / "models" / "new-model.gguf"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"gguf")
    local_model = ModelDescriptor(
        model_id="new-model",
        display_name="New Model",
        gguf_path=str(model_path),
        source="test",
        status="ready",
        backend="llama_cpp",
        n_ctx=1024,
    )

    class StopEcho:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

        def generate(self, **kwargs) -> str:
            return "[old] " + str(kwargs["user_message"])

    old_backend = StopEcho()
    rt.orchestrator.backend = old_backend
    monkeypatch.setattr(desktop_http, "discover_models", lambda *, data_root_override=None: [local_model])
    monkeypatch.setattr(
        desktop_http,
        "create_llama_backend",
        lambda *args, **kwargs: EchoBackend("new-model"),
    )
    client = create_desktop_app(rt).test_client()

    activated = client.post("/api/models/new-model/activate", json={"enabled": True})

    assert activated.status_code == 200
    payload = activated.get_json()
    assert payload["reloaded"] is True
    assert payload["active_model_id"] == "new-model"
    assert rt.model_label == "New Model"
    assert old_backend.stopped is True
    chat = client.post("/api/chat", json={"message": "ping"}).get_json()
    assert "[new-model] ping" in chat["reply"]


def test_desktop_http_cloud_activate_does_not_swap_backend(tmp_path, monkeypatch) -> None:
    rt = _runtime(tmp_path)
    old_backend = rt.orchestrator.backend
    cloud = ModelDescriptor(
        model_id="cloud-demo",
        display_name="Cloud Demo",
        gguf_path=None,
        source="test",
        status="ready",
        backend="cloud",
    )
    monkeypatch.setattr(desktop_http, "discover_models", lambda *, data_root_override=None: [cloud])
    client = create_desktop_app(rt).test_client()

    client.get("/api/auth/status")
    token = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))["token"]
    client.post("/api/auth/login", json={"token": token})
    activated = client.post("/api/models/cloud-demo/activate", json={"enabled": True})

    assert activated.status_code == 200
    assert activated.get_json()["reloaded"] is False
    assert rt.orchestrator.backend is old_backend
    assert rt.model_label == "Cloud Demo"


def test_desktop_http_model_reload_failure_keeps_old_backend(tmp_path, monkeypatch) -> None:
    rt = _runtime(tmp_path)
    old_backend = rt.orchestrator.backend
    model_path = tmp_path / "models" / "broken.gguf"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"gguf")
    broken_model = ModelDescriptor(
        model_id="broken",
        display_name="Broken",
        gguf_path=str(model_path),
        source="test",
        status="ready",
        backend="llama_cpp",
    )
    monkeypatch.setattr(desktop_http, "discover_models", lambda *, data_root_override=None: [broken_model])

    def fail_reload(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(desktop_http, "create_llama_backend", fail_reload)
    client = create_desktop_app(rt).test_client()

    activated = client.post("/api/models/broken/activate", json={"enabled": True})

    assert activated.status_code == 500
    assert activated.get_json()["error"] == "model_reload_failed"
    assert rt.orchestrator.backend is old_backend
    assert rt.model_label == ECHO_NO_MODEL_LABEL


def test_desktop_http_concurrent_model_activate_returns_409(tmp_path, monkeypatch) -> None:
    rt = _runtime(tmp_path)
    model_path = tmp_path / "models" / "slow.gguf"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"gguf")
    local_model = ModelDescriptor(
        model_id="slow",
        display_name="Slow",
        gguf_path=str(model_path),
        source="test",
        status="ready",
        backend="llama_cpp",
    )
    monkeypatch.setattr(desktop_http, "discover_models", lambda *, data_root_override=None: [local_model])
    loading_started = threading.Event()
    release_loading = threading.Event()

    def slow_reload(*args, **kwargs):
        loading_started.set()
        release_loading.wait(timeout=5)
        return EchoBackend("slow")

    monkeypatch.setattr(desktop_http, "create_llama_backend", slow_reload)
    app = create_desktop_app(rt)
    result: dict[str, int] = {}

    def activate_first() -> None:
        result["first"] = app.test_client().post("/api/models/slow/activate", json={"enabled": True}).status_code

    thread = threading.Thread(target=activate_first)
    thread.start()
    assert loading_started.wait(timeout=2)

    second = app.test_client().post("/api/models/slow/activate", json={"enabled": True})
    release_loading.set()
    thread.join(timeout=5)

    assert second.status_code == 409
    assert second.get_json()["error"] == "model_loading"
    assert result["first"] == 200


def test_desktop_http_chat_during_model_activate_returns_503(tmp_path, monkeypatch) -> None:
    rt = _runtime(tmp_path)
    model_path = tmp_path / "models" / "slow-chat.gguf"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"gguf")
    local_model = ModelDescriptor(
        model_id="slow-chat",
        display_name="Slow Chat",
        gguf_path=str(model_path),
        source="test",
        status="ready",
        backend="llama_cpp",
    )
    monkeypatch.setattr(desktop_http, "discover_models", lambda *, data_root_override=None: [local_model])
    loading_started = threading.Event()
    release_loading = threading.Event()

    def slow_reload(*args, **kwargs):
        loading_started.set()
        release_loading.wait(timeout=5)
        return EchoBackend("slow-chat")

    monkeypatch.setattr(desktop_http, "create_llama_backend", slow_reload)
    app = create_desktop_app(rt)
    result: dict[str, int] = {}

    def activate_model() -> None:
        result["activate"] = app.test_client().post("/api/models/slow-chat/activate", json={"enabled": True}).status_code

    thread = threading.Thread(target=activate_model)
    thread.start()
    assert loading_started.wait(timeout=2)

    chat = app.test_client().post("/api/chat", json={"message": "ping"})
    release_loading.set()
    thread.join(timeout=5)

    assert chat.status_code == 503
    assert chat.get_json()["error"] == "model_loading"
    assert result["activate"] == 200


def test_desktop_http_old_backend_stop_failure_does_not_fail_activate(tmp_path, monkeypatch, caplog) -> None:
    rt = _runtime(tmp_path)
    model_path = tmp_path / "models" / "new-after-stop-fail.gguf"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"gguf")
    local_model = ModelDescriptor(
        model_id="new-after-stop-fail",
        display_name="New After Stop Fail",
        gguf_path=str(model_path),
        source="test",
        status="ready",
        backend="llama_cpp",
    )

    class BrokenStopBackend:
        def stop(self) -> None:
            raise RuntimeError("stop boom")

        def generate(self, **kwargs) -> str:
            return "[old] " + str(kwargs["user_message"])

    rt.orchestrator.backend = BrokenStopBackend()
    monkeypatch.setattr(desktop_http, "discover_models", lambda *, data_root_override=None: [local_model])
    monkeypatch.setattr(desktop_http, "create_llama_backend", lambda *args, **kwargs: EchoBackend("new-after-stop-fail"))
    client = create_desktop_app(rt).test_client()

    activated = client.post("/api/models/new-after-stop-fail/activate", json={"enabled": True})

    assert activated.status_code == 200
    assert activated.get_json()["reloaded"] is True
    assert rt.model_label == "New After Stop Fail"
    assert "[new-after-stop-fail] ping" in client.post("/api/chat", json={"message": "ping"}).get_json()["reply"]
    assert "old backend stop failed after model swap" in caplog.text


def test_desktop_http_extensions_list_and_toggle(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    listed = client.get("/api/extensions")
    assert listed.status_code == 200
    items = listed.get_json()["items"]
    assert items
    assert {"id", "name", "type", "source", "status", "enabled", "version", "permissions"} <= set(items[0])

    toggled = client.post(f"/api/extensions/{items[0]['id']}/toggle", json={"enabled": False})
    assert toggled.status_code == 200
    assert toggled.get_json()["enabled"] is False


def test_desktop_http_plan_and_extension_state_survive_app_recreate(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    plan = client.post("/api/plan/decompose", json={"goal": "整理 release checklist"}).get_json()["plan"]
    paused = client.post(f"/api/plan/{plan['id']}/pause")
    assert paused.status_code == 200
    extension_id = client.get("/api/extensions").get_json()["items"][0]["id"]
    toggled = client.post(f"/api/extensions/{extension_id}/toggle", json={"enabled": False})
    assert toggled.status_code == 200

    recreated = create_desktop_app(rt).test_client()
    resumed = recreated.post(f"/api/plan/{plan['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.get_json()["plan"]["status"] == "running"
    db_plan = rt.orchestrator.conn.execute(
        "SELECT status FROM plans WHERE plan_id = ?;",
        (plan["id"],),
    ).fetchone()
    assert db_plan["status"] == "running"
    extensions = recreated.get("/api/extensions").get_json()["items"]
    restored_extension = next(item for item in extensions if item["id"] == extension_id)
    assert restored_extension["enabled"] is False


def test_desktop_http_plan_cancel_deletes_sqlite_row(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()
    plan = client.post("/api/plan/decompose", json={"goal": "整理临时计划"}).get_json()["plan"]

    cancelled = client.post(f"/api/plan/{plan['id']}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.get_json()["plan"]["status"] == "cancelled"
    row = rt.orchestrator.conn.execute(
        "SELECT COUNT(*) AS c FROM plans WHERE plan_id = ?;",
        (plan["id"],),
    ).fetchone()
    assert int(row["c"]) == 0


def test_desktop_http_legacy_extension_json_migrates_to_sqlite(tmp_path) -> None:
    rt = _runtime(tmp_path)
    extension_id = create_desktop_app(rt).test_client().get("/api/extensions").get_json()["items"][0]["id"]
    (tmp_path / "extension_state.json").write_text(
        json.dumps({"enabled": {extension_id: False}}, ensure_ascii=False),
        encoding="utf-8",
    )

    client = create_desktop_app(rt).test_client()
    extensions = client.get("/api/extensions").get_json()["items"]
    restored_extension = next(item for item in extensions if item["id"] == extension_id)

    assert restored_extension["enabled"] is False
    assert (tmp_path / "extension_state.json.bak").is_file()
    row = rt.orchestrator.conn.execute(
        "SELECT enabled FROM extension_status WHERE extension_id = ?;",
        (extension_id,),
    ).fetchone()
    assert bool(row["enabled"]) is False


def test_desktop_http_missing_extension_status_defaults_enabled(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    extensions = client.get("/api/extensions").get_json()["items"]

    assert extensions
    assert extensions[0]["enabled"] is True


def test_desktop_http_corrupt_persistent_state_falls_back_to_empty(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    missing_plan = client.post("/api/plan/plan_missing/resume")
    assert missing_plan.status_code == 404
    assert client.get("/api/extensions").status_code == 200


def test_desktop_http_settings_missing_and_corrupt_fall_back_to_defaults(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    missing = client.get("/api/settings")

    assert missing.status_code == 200
    missing_settings = missing.get_json()["settings"]
    assert missing_settings["theme"] == "light"
    assert missing.get_json()["settings_path"] == str(tmp_path / "settings.json")
    assert missing_settings["last_view"] == "chat"
    assert missing_settings["shell_custom"]["accent"] is None
    assert missing_settings["active_persona_id"] is None
    assert missing_settings["close_to_tray"] is True
    (tmp_path / "settings.json").write_text("{bad", encoding="utf-8")
    corrupt = create_desktop_app(rt).test_client().get("/api/settings")
    assert corrupt.status_code == 200
    assert corrupt.get_json()["settings"]["privacy_mode"] == PrivacyMode.LOCAL_ONLY.value


def test_desktop_http_settings_loads_utf8_bom_json(tmp_path) -> None:
    rt = _runtime(tmp_path)
    (tmp_path / "settings.json").write_text('{"theme": "dark", "last_view": "persona"}', encoding="utf-8-sig")

    settings = create_desktop_app(rt).test_client().get("/api/settings").get_json()["settings"]

    assert settings["theme"] == "dark"
    assert settings["last_view"] == "persona"


def test_desktop_http_settings_persist_across_app_recreate(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    saved = client.post(
        "/api/settings",
        json={
            "theme": "dark",
            "privacy_mode": PrivacyMode.AUTO_ROUTE_CLOUD.value,
            "auto_router_enabled": True,
            "close_to_tray": False,
        },
    )

    assert saved.status_code == 200
    assert saved.get_json()["settings"]["theme"] == "dark"
    recreated = create_desktop_app(rt).test_client()
    status = recreated.get("/api/status").get_json()
    models = recreated.get("/api/models").get_json()
    settings = recreated.get("/api/settings").get_json()["settings"]
    assert status["privacy_mode"] == PrivacyMode.AUTO_ROUTE_CLOUD.value
    assert settings["theme"] == "dark"
    assert settings["close_to_tray"] is False
    assert models["auto"] is True


def test_desktop_http_privacy_and_auto_update_settings(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    privacy = client.post("/api/privacy/mode", json={"mode": "CLOUD"})
    auto = client.post("/api/models/auto", json={"enabled": True})

    assert privacy.status_code == 200
    assert auto.status_code == 200
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["privacy_mode"] == PrivacyMode.AUTO_ROUTE_CLOUD.value
    assert saved["auto_router_enabled"] is True


def test_desktop_http_feedback_privacy_and_reaction(tmp_path) -> None:
    rt = _runtime(tmp_path)
    message_id = append_message(rt.orchestrator.conn, "h1", "assistant", "可反馈消息", {})
    client = create_desktop_app(rt).test_client()

    mode = client.post("/api/privacy/mode", json={"mode": "CLOUD"})
    assert mode.status_code == 200
    assert mode.get_json()["privacy_mode"] == PrivacyMode.AUTO_ROUTE_CLOUD.value
    assert rt.privacy_mode is PrivacyMode.AUTO_ROUTE_CLOUD
    assert rt.orchestrator.privacy_mode is PrivacyMode.AUTO_ROUTE_CLOUD

    feedback = client.post("/api/feedback", json={"msg_id": message_id, "type": "error", "comment": "bad"})
    assert feedback.status_code == 200
    assert feedback.get_json()["queued"] is True
    lines = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["comment"] == "bad"
    assert json.loads(lines[-1])["queueable"] is False

    reaction = client.post("/api/message/react", json={"msg_id": message_id, "emoji": "👍"})
    assert reaction.status_code == 200
    meta = rt.orchestrator.conn.execute(
        "SELECT meta_json FROM messages WHERE id = ?;",
        (message_id,),
    ).fetchone()["meta_json"]
    assert json.loads(meta)["reactions"][0]["emoji"] == "👍"


def test_desktop_http_privacy_mode_hot_switches_socket_guard(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    try:
        local = client.post("/api/privacy/mode", json={"mode": "LOCAL_ONLY"})
        assert local.status_code == 200
        assert local.get_json()["socket_guard_enabled"] is True
        assert local.get_json()["existing_connections"] == "unchanged"
        assert rt.socket_guard_enabled is True
        assert is_socket_guard_enabled() is True

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            assert isinstance(sock.connect_ex(("127.0.0.1", 9)), int)
        with pytest.raises(OutboundDenied):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("93.184.216.34", 80))

        cloud = client.post("/api/privacy/mode", json={"mode": "CLOUD"})
        assert cloud.status_code == 200
        assert cloud.get_json()["socket_guard_enabled"] is False
        assert rt.socket_guard_enabled is False
        assert is_socket_guard_enabled() is False
    finally:
        disable_privacy_socket_guard()


def test_desktop_http_auth_and_improve_plan_flow(tmp_path) -> None:
    rt = _runtime(tmp_path)
    client = create_desktop_app(rt).test_client()

    status = client.get("/api/auth/status")
    assert status.status_code == 200
    assert status.get_json()["logged_in"] is False
    assert (tmp_path / "auth.json").is_file()

    blocked = client.post("/api/improve-plan", json={"enabled": True})
    assert blocked.status_code == 403
    assert blocked.get_json()["error"] == "requires_login_and_cloud"

    bad_login = client.post("/api/auth/login", json={"token": "bad"})
    assert bad_login.status_code == 401

    token = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))["token"]
    login = client.post("/api/auth/login", json={"token": token})
    assert login.status_code == 200
    assert login.get_json()["logged_in"] is True
    assert client.get("/api/status").get_json()["logged_in"] is True

    still_blocked = client.post("/api/improve-plan", json={"enabled": True})
    assert still_blocked.status_code == 403

    client.post("/api/privacy/mode", json={"mode": "CLOUD"})
    enabled = client.post("/api/improve-plan", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.get_json()["enabled"] is True

    message_id = append_message(rt.orchestrator.conn, "h1", "assistant", "可反馈消息", {})
    feedback = client.post("/api/feedback", json={"msg_id": message_id, "type": "error"})
    assert feedback.status_code == 200
    lines = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["queueable"] is True
    assert client.get("/api/improve-plan").get_json()["queued_count"] == 1

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.get_json()["logged_in"] is False
    assert client.get("/api/improve-plan").get_json()["enabled"] is False


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


def test_desktop_http_chat_stream_cloud_route_returns_single_done(tmp_path) -> None:
    rt = _runtime(tmp_path)
    rt.orchestrator.privacy_mode = PrivacyMode.AUTO_ROUTE_CLOUD
    rt.orchestrator.model_router = _HttpRouter(
        ModelRoutingDecision(
            selected_model="deepseek-v4",
            fallback_model="qwen2.5-1.5b-instruct-q4_k_m",
            requires_consent=False,
            reason="cloud_candidate_selected",
            estimated_input_tokens=100,
            estimated_output_tokens=200,
            estimated_cost=0.02,
        ),
        selected_type="cloud",
    )
    rt.orchestrator.cloud_post = lambda _req: CloudCompletionResponse(text="cloud reply", raw={})
    client = create_desktop_app(rt).test_client()

    response = client.post("/api/chat", json={"message": "cloud please", "stream": True})

    events = _sse_payloads(response.text)
    assert len(events) == 1
    assert events[0]["done"] is True
    assert "cloud reply" in events[0]["reply"]
    assert events[0]["route_mode"] == "cloud"
