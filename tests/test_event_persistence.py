"""事件流 SQLite 持久化测试。"""

from __future__ import annotations

import sqlite3

from offline_companion.core.event_stream import (
    EventPersistence,
    StreamManager,
    build_default_registry,
)


def wait_for_events(persistence: EventPersistence) -> None:
    """等待测试事件完成 write-behind。"""
    persistence.flush(timeout=2)


def test_append_is_written_to_domain_events_and_restored(tmp_path) -> None:
    db_path = tmp_path / "events.db"
    registry = build_default_registry()
    persistence = EventPersistence(db_path)
    manager = StreamManager(registry, persistence)

    stream = manager.get_or_create("session-1")
    stream.append("session/created", {"session_id": "session-1"})
    stream.append("session/message", {"role": "user", "content": "hi"})
    wait_for_events(persistence)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM domain_events").fetchone()[0] == 2
    persistence.shutdown()

    restored_persistence = EventPersistence(db_path)
    restored_manager = StreamManager(registry, restored_persistence)
    restored_manager.restore_from_disk()
    restored = restored_manager.get("session-1")
    assert restored is not None
    assert [event.seq for event in restored.get_events()] == [0, 1]
    restored_persistence.shutdown()


def test_multiple_streams_keep_independent_sequences(tmp_path) -> None:
    persistence = EventPersistence(tmp_path / "events.db")
    manager = StreamManager(build_default_registry(), persistence)

    manager.get_or_create("first").append("session/created", {})
    manager.get_or_create("second").append("session/created", {})
    wait_for_events(persistence)

    assert {stream_id: len(events) for stream_id, events in persistence.load_all_streams().items()} == {
        "first": 1,
        "second": 1,
    }
    persistence.shutdown()


def test_duplicate_event_id_is_idempotent(tmp_path) -> None:
    persistence = EventPersistence(tmp_path / "events.db")
    event = StreamManager(build_default_registry(), persistence).get_or_create("s").append(
        "session/created", {}
    )
    wait_for_events(persistence)
    persistence._write_queue.put(event)
    wait_for_events(persistence)

    assert len(persistence.load_stream("s")) == 1
    persistence.shutdown()


def test_seq_gap_truncates_loaded_prefix_and_marks_recovery(tmp_path, caplog) -> None:
    db_path = tmp_path / "events.db"
    persistence = EventPersistence(db_path)
    manager = StreamManager(build_default_registry(), persistence)
    stream = manager.get_or_create("s")
    stream.append("session/created", {})
    stream.append("session/message", {"role": "user"})
    stream.append("session/turn_end", {})
    wait_for_events(persistence)
    persistence.shutdown()

    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM domain_events WHERE stream_id = 's' AND seq = 1")
        connection.commit()

    recovered_persistence = EventPersistence(db_path)
    events = recovered_persistence.load_stream("s")

    assert [event.seq for event in events] == [0]
    assert recovered_persistence.recovery_mode is True
    assert "seq 不连续" in caplog.text
    recovered_persistence.shutdown()


def test_enqueue_remains_non_blocking_when_writer_connection_fails(tmp_path) -> None:
    persistence = EventPersistence(tmp_path / "events.db")
    manager = StreamManager(build_default_registry(), persistence)
    stream = manager.get_or_create("s")
    persistence._conn.close()

    event = stream.append("session/created", {})

    assert event.seq == 0
    persistence.shutdown()


def test_seq_gap_deletes_orphaned_events_before_next_append(tmp_path) -> None:
    db_path = tmp_path / "events.db"
    persistence = EventPersistence(db_path)
    manager = StreamManager(build_default_registry(), persistence)
    stream = manager.get_or_create("s")
    stream.append("session/created", {})
    stream.append("session/message", {"role": "user"})
    stream.append("session/turn_end", {})
    wait_for_events(persistence)
    persistence.shutdown()

    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM domain_events WHERE stream_id = 's' AND seq = 1")
        connection.commit()

    recovered_persistence = EventPersistence(db_path)
    recovered_manager = StreamManager(build_default_registry(), recovered_persistence)
    recovered_manager.restore_from_disk()
    recovered_stream = recovered_manager.get("s")
    assert recovered_stream is not None
    recovered_stream.append("session/message", {"role": "assistant"})
    wait_for_events(recovered_persistence)

    loaded = recovered_persistence.load_stream("s")
    assert [event.seq for event in loaded] == [0, 1]
    assert loaded[-1].payload == {"role": "assistant"}
    recovered_persistence.shutdown()
