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
        events.append((new_record.domain, new_record.key, new_record.value, None if old_record is None else old_record.value))

    sm.subscribe("task", "progress", on_change)
    sm.set_task_state("progress", 0.7)
    sm.set_task_state("progress", 0.9)

    assert events[0] == ("task", "progress", 0.7, None)
    assert events[1] == ("task", "progress", 0.9, 0.7)
