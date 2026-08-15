"""EventStream 与 StreamManager 测试。"""

from __future__ import annotations

from offline_companion.core.event_stream import (
    EventStream,
    StreamManager,
    build_default_registry,
)


def make_stream() -> EventStream:
    """创建测试用事件流。"""
    return EventStream("test-stream", build_default_registry())


def test_append_assigns_contiguous_sequences() -> None:
    stream = make_stream()

    first = stream.append("session/created", {"session_id": "s1"})
    second = stream.append("session/message", {"role": "user", "content": "hello"})

    assert (first.seq, second.seq) == (0, 1)
    assert stream.latest_seq == 1
    assert stream.get_events() == [first, second]


def test_append_rejects_unknown_type_without_mutating_stream() -> None:
    stream = make_stream()

    try:
        stream.append("missing/event", {})
    except ValueError as exc:
        assert "未知" in str(exc)
    else:
        raise AssertionError("未知事件类型必须被拒绝")

    assert stream.latest_seq == -1
    assert stream.get_events() == []


def test_append_rejects_non_json_payload_without_mutating_stream() -> None:
    stream = make_stream()

    try:
        stream.append("session/message", {"content": object()})
    except ValueError:
        pass
    else:
        raise AssertionError("不可序列化 payload 必须被拒绝")

    assert stream.get_events() == []


def test_observer_receives_committed_event() -> None:
    stream = make_stream()
    received = []
    stream.subscribe(received.append)

    event = stream.append("session/created", {})

    assert received == [event]


def test_unsubscribe_stops_observer_notifications() -> None:
    stream = make_stream()
    received = []
    unsubscribe = stream.subscribe(received.append)
    unsubscribe()

    stream.append("session/created", {})

    assert received == []


def test_observer_failure_does_not_rollback_or_block_other_observers(caplog) -> None:
    stream = make_stream()
    received = []

    def failing_observer(_event) -> None:
        raise RuntimeError("observer failed")

    stream.subscribe(failing_observer)
    stream.subscribe(received.append)

    event = stream.append("session/created", {})

    assert stream.get_event(0) == event
    assert received == [event]
    assert "observer 通知失败" in caplog.text


def test_reentrant_append_is_rejected_after_outer_event_is_committed() -> None:
    stream = make_stream()
    errors = []

    def reentrant_observer(_event) -> None:
        try:
            stream.append("session/message", {"role": "assistant"})
        except RuntimeError as exc:
            errors.append(str(exc))

    stream.subscribe(reentrant_observer)
    event = stream.append("session/created", {})

    assert errors == ["检测到事件流 append 重入"]
    assert stream.get_events() == [event]


def test_get_events_returns_from_sequence_and_empty_for_invalid_sequence() -> None:
    stream = make_stream()
    events = [stream.append("session/created", {"index": index}) for index in range(3)]

    assert stream.get_events(from_seq=1) == events[1:]
    assert stream.get_events(from_seq=-1) == []
    assert stream.get_events(from_seq=3) == []


def test_stream_manager_keeps_streams_and_sequences_independent() -> None:
    manager = StreamManager(build_default_registry())

    first = manager.get_or_create("first")
    second = manager.get_or_create("second")
    first_event = first.append("session/created", {})
    second_event = second.append("session/created", {})

    assert manager.get_or_create("first") is first
    assert manager.get("missing") is None
    assert (first_event.stream_id, second_event.stream_id) == ("first", "second")
    assert (first_event.seq, second_event.seq) == (0, 0)
