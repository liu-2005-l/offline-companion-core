"""Trajectory Projection 测试。"""

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.event_stream.projection import Projection, build_trajectory_projection


def test_projection_registry_routes_events_to_handlers() -> None:
    projection = Projection()
    seen = []

    @projection.on("test/event")
    def handle(event, state):
        seen.append(event.seq)
        state["summary"]["handled"] = True

    event = EventStream("s", build_default_registry()).append("session/created", {})
    event = event.__class__(
        event_id=event.event_id,
        stream_id=event.stream_id,
        seq=event.seq,
        event_type="test/event",
        timestamp=event.timestamp,
        schema_version=event.schema_version,
        payload=event.payload,
    )

    result = projection.project([event])

    assert seen == [0]
    assert result["summary"]["handled"] is True


def test_trajectory_projects_turn_steps_and_terminal_events() -> None:
    stream = EventStream("s", build_default_registry())
    stream.append("session/turn_start", {"trace_id": "t1"})
    stream.append("plan/step_started", {"step_title": "读取文件", "trace_id": "t1"})
    stream.append("plan/step_completed", {"step_id": "s1", "trace_id": "t1"})
    stream.append("session/turn_end", {"status": "completed", "trace_id": "t1"})

    result = build_trajectory_projection().project(stream.get_events())

    assert [item["type"] for item in result["timeline"]] == [
        "turn_start",
        "step_started",
        "step_completed",
        "turn_end",
    ]
    assert result["summary"]["current_step"] == "读取文件"
    assert result["summary"]["event_count"] == 4


def test_empty_trajectory_is_empty() -> None:
    assert build_trajectory_projection().project([]) == {
        "timeline": [],
        "summary": {"event_count": 0},
    }


def test_trajectory_projection_filters_by_trace_id() -> None:
    stream = EventStream("s", build_default_registry())
    stream.append("session/turn_start", {"trace_id": "t1"})
    stream.append("session/turn_start", {"trace_id": "t2"})

    result = build_trajectory_projection().project(stream.get_events(), "t2")

    assert result["summary"]["event_count"] == 1
    assert result["timeline"][0]["trace_id"] == "t2"
