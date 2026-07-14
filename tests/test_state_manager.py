from __future__ import annotations

from pathlib import Path

from offline_companion.core.state_manager import StateManager


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

    sm.subscribe("task", "progress", on_change)
    sm.set_task_state("progress", 0.7)
    sm.set_task_state("progress", 0.9)

    assert events[0] == ("task", "progress", 0.7, None)
    assert events[1] == ("task", "progress", 0.9, 0.7)


def test_state_manager_unsubscribe_stops_notifications(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    events: list[object] = []

    def on_change(new_record, old_record) -> None:
        events.append(new_record.value)

    sm.subscribe("system", "mode", on_change)
    assert sm.unsubscribe("system", "mode", on_change)
    sm.set_system_state("mode", "auto")

    assert events == []


def test_state_manager_wildcard_subscription(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    events: list[tuple[str, str, object]] = []

    def on_change(new_record, old_record) -> None:
        events.append((new_record.domain, new_record.key, new_record.value))

    sm.subscribe("task", "*", on_change)
    sm.set_task_state("status", "running")
    sm.set_task_state("progress", 1.0)

    assert events == [("task", "status", "running"), ("task", "progress", 1.0)]


def test_state_manager_records_callback_errors(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")

    def failing_callback(new_record, old_record) -> None:
        raise RuntimeError("boom")

    sm.subscribe("session", "active", failing_callback)
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

    sm.subscribe("session", "active", failing_callback)
    sm.set_session_state("active", True)
    assert sm.get_event_errors()
    sm.clear_event_errors()
    assert sm.get_event_errors() == []


def test_state_manager_trigger_idle_think(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    events: list[bool] = []

    def on_idle_request(new_record, old_record) -> None:
        events.append(bool(new_record.value))

    sm.subscribe("system", "idle_think_requested", on_idle_request)
    sm.trigger_idle_think()

    assert sm.get_system_state("idle_think_requested") is True
    assert events == [True]
