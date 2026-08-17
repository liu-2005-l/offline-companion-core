"""Trajectory API 与开发模式面板测试。"""

from tests.test_desktop_http import _runtime

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app


def test_trajectory_endpoint_returns_projected_events(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    stream = EventStream("h1", build_default_registry())
    stream.append("session/turn_start", {"trace_id": "trace-1"})
    stream.append("model/switched", {"model": "local"})
    runtime.event_stream_manager = type("Manager", (), {"get": lambda self, stream_id: stream})()
    client = create_desktop_app(runtime).test_client()

    response = client.get("/api/trajectory/h1")

    assert response.status_code == 200
    payload = response.get_json()
    assert [item["type"] for item in payload["timeline"]] == ["turn_start", "model_switched"]
    assert payload["summary"]["event_count"] == 2


def test_trajectory_endpoint_filters_by_trace_id(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    stream = EventStream("h1", build_default_registry())
    stream.append("session/turn_start", {"trace_id": "trace-1"})
    stream.append("session/turn_start", {"trace_id": "trace-2"})
    runtime.event_stream_manager = type("Manager", (), {"get": lambda self, stream_id: stream})()
    client = create_desktop_app(runtime).test_client()

    response = client.get("/api/trajectory/h1?trace_id=trace-2")

    assert response.get_json()["summary"]["event_count"] == 1


def test_trajectory_endpoint_returns_empty_for_unknown_stream(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()

    response = client.get("/api/trajectory/missing")

    assert response.get_json() == {"timeline": [], "summary": {"event_count": 0}}
