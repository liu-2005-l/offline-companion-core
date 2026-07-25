from __future__ import annotations

from pathlib import Path

from offline_companion.core.state_manager import (
    StateAccessError,
    StateEventFormatError,
    StateManager,
    StateVersionConflictError,
)


def test_state_manager_domain_roundtrip(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    sm.set_session_state("session_id", "s-1")
    sm.set_task_state("progress", 0.5)
    sm.set_system_state("mode", "auto")

    assert sm.get_session_state("session_id") == "s-1"
    assert sm.get_task_state("progress") == 0.5
    assert sm.get_system_state("mode") == "auto"


def test_state_manager_subscribe_triggers_on_update(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    events: list[tuple[str, str, object, object | None]] = []

    def on_change(new_record, old_record) -> None:
        events.append(
            (
                new_record.domain,
                new_record.key,
                new_record.value,
                None if old_record is None else old_record.value,
            )
        )

    sm.subscribe("task", "progress", on_change, role="task")
    sm.set_task_state("progress", 0.7)
    sm.set_task_state("progress", 0.9)

    assert events[0] == ("task", "progress", 0.7, None)
    assert events[1] == ("task", "progress", 0.9, 0.7)


def test_state_manager_unsubscribe_stops_notifications(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    events: list[object] = []

    def on_change(new_record, old_record) -> None:
        events.append(new_record.value)

    sm.subscribe("system", "mode", on_change, role="system")
    assert sm.unsubscribe("system", "mode", on_change, role="system")
    sm.set_system_state("mode", "auto")

    assert events == []


def test_state_manager_wildcard_subscription(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    events: list[tuple[str, str, object]] = []

    def on_change(new_record, old_record) -> None:
        events.append((new_record.domain, new_record.key, new_record.value))

    sm.subscribe("task", "*", on_change, role="task")
    sm.set_task_state("status", "running")
    sm.set_task_state("progress", 1.0)

    assert events == [("task", "status", "running"), ("task", "progress", 1.0)]


def test_state_manager_records_callback_errors(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")

    def failing_callback(new_record, old_record) -> None:
        raise RuntimeError("boom")

    sm.subscribe("session", "active", failing_callback, role="session")
    sm.set_session_state("active", True)

    errors = sm.get_event_errors()
    assert len(errors) == 1
    assert errors[0].domain == "session"
    assert errors[0].key == "active"
    assert errors[0].error == "boom"


def test_state_manager_clear_event_errors(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")

    def failing_callback(new_record, old_record) -> None:
        raise RuntimeError("boom")

    sm.subscribe("session", "active", failing_callback, role="session")
    sm.set_session_state("active", True)
    assert sm.get_event_errors()
    sm.clear_event_errors()
    assert sm.get_event_errors() == []


def test_state_manager_rejects_invalid_domain(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")

    try:
        sm.set("invalid", "key", "value")
    except StateAccessError as exc:
        assert exc.code == "E_STATE_DOMAIN_DENIED"
    else:  # pragma: no cover - safety guard
        raise AssertionError("expected StateAccessError")


def test_state_manager_version_conflict(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    record = sm.set_task_state("progress", 0.1)

    try:
        sm.set_if_version("task", "progress", 0.2, expected_version=record.version + 1)
    except StateVersionConflictError as exc:
        assert exc.code == "E_STATE_VERSION_CONFLICT"
    else:  # pragma: no cover - safety guard
        raise AssertionError("expected StateVersionConflictError")


def test_state_manager_rejects_invalid_event_name(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")

    try:
        sm.publish_event("system", "InvalidEvent", {"trace_id": "t-1", "data": {}})
    except StateEventFormatError as exc:
        assert exc.code == "E_STATE_EVENT_INVALID"
    else:  # pragma: no cover - safety guard
        raise AssertionError("expected StateEventFormatError")


def test_state_manager_records_audit_log(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    sm.set_system_state("mode", "auto")
    row = sm._conn.execute(
        "SELECT domain, key, actor, operation, version FROM state_audit_log LIMIT 1;"
    ).fetchone()

    assert tuple(row) == ("system", "mode", "system", "set", 1)


def test_state_manager_rejects_role_mismatch(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")

    try:
        sm.set_task_state("progress", 1.0, role="session")
    except StateAccessError as exc:
        assert exc.code == "E_STATE_DOMAIN_DENIED"
    else:  # pragma: no cover - safety guard
        raise AssertionError("expected StateAccessError")
