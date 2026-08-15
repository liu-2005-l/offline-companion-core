from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.messages import BaseMessage, MessageDirection
from offline_companion.shell.auto_router import (
    AutoRouter,
    AutoRoutingAdapter,
    RoutingContext,
    RoutingMode,
)
from offline_companion.shell.message_router import MessageRouter


def test_message_router_routes_registered_namespace() -> None:
    router = MessageRouter()
    events: list[str] = []

    router.register("task", lambda message: events.append(message.topic))
    router.route(
        BaseMessage(
            message_id="m-1",
            topic="task.progress",
            source="shell",
            direction=MessageDirection.INTERNAL,
        )
    )

    assert events == ["task.progress"]


def test_message_router_uses_wildcard_handler() -> None:
    router = MessageRouter()
    events: list[str] = []

    router.register_wildcard(lambda message: events.append(message.topic))
    router.route(
        BaseMessage(
            message_id="m-2",
            topic="unknown.topic",
            source="shell",
            direction=MessageDirection.INTERNAL,
        )
    )

    assert events == ["unknown.topic"]


def test_message_router_applies_auto_routing_meta() -> None:
    router = MessageRouter()
    events: list[BaseMessage] = []
    auto_router = AutoRouter(complexity_threshold=3)
    adapter = AutoRoutingAdapter(
        auto_router,
        lambda message: RoutingContext(
            query=message.topic,
            privacy_mode="local_only" if message.meta.get("local_only") else "hybrid",
            complexity=int(message.meta.get("complexity", 0)),
            cloud_cost=float(message.meta.get("cloud_cost", 0.0)),
            cloud_budget=float(message.meta.get("cloud_budget", 1.0)),
            metadata=dict(message.meta),
        ),
    )
    router.register_auto_router(adapter)
    router.register("task", lambda message: events.append(message))

    router.route(
        BaseMessage(
            message_id="m-3",
            topic="task.plan",
            source="shell",
            direction=MessageDirection.INTERNAL,
            meta={"complexity": 10, "cloud_cost": 0.2, "cloud_budget": 1.0},
        )
    )

    assert events[0].meta["auto_route"] == RoutingMode.CLOUD.value
    assert events[0].meta["auto_route_reason"] == "complexity_threshold_exceeded"


def test_message_router_dispatch_records_idempotent_result(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    router.register("task", lambda message: {"ok": message.payload["value"]})

    message = BaseMessage(
        message_id="m-10",
        topic="task.run",
        source="shell",
        direction=MessageDirection.INTERNAL,
        session_id="s-1",
        idempotency_key="idem-1",
        payload={"value": 7},
    )
    first = router.dispatch(message)
    second = router.dispatch(message)

    assert first.status == "completed"
    assert first.result == {"ok": 7}
    assert second.status == "skipped_duplicate"
    row = conn.execute(
        "SELECT status, result FROM message_execution_records WHERE idempotency_key = ?;",
        ("idem-1",),
    ).fetchone()
    assert row["status"] == "completed"


def test_message_router_dispatch_sends_failed_message_to_dlq(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)

    def _boom(message: BaseMessage) -> object:
        raise RuntimeError("boom")

    router.register("task", _boom)
    result = router.dispatch(
        BaseMessage(
            message_id="m-11",
            topic="task.fail",
            source="shell",
            session_id="s-1",
            idempotency_key="idem-2",
        )
    )

    assert result.status == "failed"
    row = conn.execute(
        "SELECT session_id, handler_namespace, error FROM dead_letter_queue WHERE original_message_id = ?;",
        ("m-11",),
    ).fetchone()
    assert row["session_id"] == "s-1"
    assert row["handler_namespace"] == "task"


def test_message_router_dialog_queue_serializes_same_session(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    events: list[str] = []

    def _handler(message: BaseMessage) -> object:
        events.append(f"start-{message.message_id}")
        time.sleep(0.05)
        events.append(f"end-{message.message_id}")
        return message.message_id

    router.register("task", _handler)
    barrier = threading.Barrier(2)

    def _run(message_id: str) -> None:
        barrier.wait()
        router.dispatch(
            BaseMessage(
                message_id=message_id,
                topic="task.serial",
                source="shell",
                session_id="s-1",
            )
        )

    t1 = threading.Thread(target=_run, args=("m-21",))
    t2 = threading.Thread(target=_run, args=("m-22",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert events in (
        ["start-m-21", "end-m-21", "start-m-22", "end-m-22"],
        ["start-m-22", "end-m-22", "start-m-21", "end-m-21"],
    )


def test_message_router_background_queue_allows_parallel(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    active = 0
    peak = 0
    guard = threading.Lock()

    def _handler(message: BaseMessage) -> object:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return message.message_id

    router.register("task", _handler)
    barrier = threading.Barrier(2)

    def _run(message_id: str) -> None:
        barrier.wait()
        router.dispatch(
            BaseMessage(
                message_id=message_id,
                topic="task.parallel",
                source="shell",
                session_id="s-1",
                queue_type="background",
            )
        )

    t1 = threading.Thread(target=_run, args=("m-31",))
    t2 = threading.Thread(target=_run, args=("m-32",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert peak >= 2


def test_message_router_timeout_returns_timeout_result(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    attempts = 0

    def _timeout_once(message: BaseMessage) -> object:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("synthetic timeout")

    router._execute_with_timeout = _timeout_once  # type: ignore[method-assign]

    started = time.perf_counter()
    result = router.dispatch(
        BaseMessage(
            message_id="m-41",
            topic="task.timeout",
            source="shell",
            session_id="s-1",
            timeout_sec=0.01,
            idempotency_key="idem-timeout",
        )
    )
    elapsed = time.perf_counter() - started

    assert result.status == "timeout"
    assert attempts == 2
    assert elapsed < 0.5
    row = conn.execute(
        "SELECT status FROM message_execution_records WHERE idempotency_key = ?;",
        ("idem-timeout",),
    ).fetchone()
    assert row["status"] == "failed"


def test_message_router_timeout_does_not_wait_for_slow_handler() -> None:
    router = MessageRouter()
    handler_started = threading.Event()
    release_handler = threading.Event()

    def _slow_handler(message: BaseMessage) -> object:
        handler_started.set()
        release_handler.wait(timeout=1.0)
        return message.message_id

    router.register("task", _slow_handler)
    message = BaseMessage(
        message_id="m-real-timeout",
        topic="task.timeout",
        source="shell",
        timeout_sec=0.02,
    )

    started = time.perf_counter()
    try:
        with pytest.raises(TimeoutError):
            router._execute_with_timeout(message)
        elapsed = time.perf_counter() - started
    finally:
        release_handler.set()

    assert handler_started.is_set()
    assert elapsed < 0.3


def test_message_router_retries_handler_once_then_succeeds(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    calls = 0

    def _handler(message: BaseMessage) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom-once")
        return {"ok": True}

    router.register("task", _handler)
    result = router.dispatch(
        BaseMessage(
            message_id="m-51",
            topic="task.retry",
            source="shell",
            session_id="s-1",
            idempotency_key="idem-retry-success",
        )
    )

    assert result.status == "completed"
    assert result.result == {"ok": True}
    assert calls == 2


def test_message_router_retries_handler_once_then_sends_dlq(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    calls = 0

    def _handler(message: BaseMessage) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom-twice")

    router.register("task", _handler)
    result = router.dispatch(
        BaseMessage(
            message_id="m-52",
            topic="task.retry.fail",
            source="shell",
            session_id="s-1",
            idempotency_key="idem-retry-fail",
        )
    )

    assert result.status == "failed"
    assert calls == 2
    row = conn.execute(
        "SELECT retry_count, error FROM dead_letter_queue WHERE original_message_id = ?;",
        ("m-52",),
    ).fetchone()
    assert row["retry_count"] == 1
    assert "E_MESSAGE_HANDLER_FAILED" in row["error"]


def test_message_router_retries_timeout_once_then_sends_dlq(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    calls = 0

    def _timeout_twice(message: BaseMessage) -> object:
        nonlocal calls
        calls += 1
        raise TimeoutError("synthetic retry timeout")

    router._execute_with_timeout = _timeout_twice  # type: ignore[method-assign]
    result = router.dispatch(
        BaseMessage(
            message_id="m-53",
            topic="task.retry.timeout",
            source="shell",
            session_id="s-1",
            timeout_sec=0.01,
            idempotency_key="idem-retry-timeout",
        )
    )

    assert result.status == "timeout"
    assert calls == 2
    row = conn.execute(
        "SELECT retry_count, error FROM dead_letter_queue WHERE original_message_id = ?;",
        ("m-53",),
    ).fetchone()
    assert row["retry_count"] == 1
    assert "E_MESSAGE_TIMEOUT" in row["error"]


def test_message_router_retry_idempotency_recheck_returns_completed(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    calls = 0

    def _handler(message: BaseMessage) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            conn.execute(
                """
                INSERT INTO message_execution_records(
                    idempotency_key, message_id, session_id, handler_namespace,
                    status, result, error, created_at, completed_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    status = excluded.status,
                    result = excluded.result,
                    error = excluded.error,
                    completed_at = excluded.completed_at;
                """,
                (
                    "idem-recheck",
                    "m-54",
                    "s-1",
                    "task",
                    "completed",
                    '{"ok": true}',
                    None,
                    "2026-07-26T00:00:00+00:00",
                    "2026-07-26T00:00:00+00:00",
                ),
            )
            raise RuntimeError("first failed after side effect")
        return {"should_not_run": True}

    router.register("task", _handler)
    result = router.dispatch(
        BaseMessage(
            message_id="m-54",
            topic="task.retry.recheck",
            source="shell",
            session_id="s-1",
            idempotency_key="idem-recheck",
        )
    )

    assert result.status == "skipped_duplicate"
    assert result.result == {"ok": True}
    assert calls == 1


def test_message_router_dialog_queue_does_not_retry_sqlite_conflict(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    calls = 0

    def _handler(message: BaseMessage) -> object:
        nonlocal calls
        calls += 1
        raise sqlite3.OperationalError("database is locked")

    router.register("task", _handler)
    result = router.dispatch(
        BaseMessage(
            message_id="m-55",
            topic="task.sqlite.locked",
            source="shell",
            session_id="s-1",
            queue_type="dialog",
            idempotency_key="idem-dialog-locked",
        )
    )

    assert result.status == "failed"
    assert calls == 1
    row = conn.execute(
        "SELECT retry_count, error FROM dead_letter_queue WHERE original_message_id = ?;",
        ("m-55",),
    ).fetchone()
    assert row["retry_count"] == 0
    assert "E_MESSAGE_SQLITE_CONFLICT" in row["error"]


def test_background_long_running_does_not_block_same_session_dialog(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    background_started = threading.Event()
    release_background = threading.Event()

    def _handler(message: BaseMessage) -> object:
        if message.queue_type == "background":
            background_started.set()
            release_background.wait(timeout=1.0)
            return {"queue": "background"}
        return {"queue": "dialog"}

    router.register("task", _handler)
    background_result: dict[str, object] = {}

    def _run_background() -> None:
        background_result["result"] = router.dispatch(
            BaseMessage(
                message_id="m-61",
                topic="task.long",
                source="shell",
                session_id="s-1",
                queue_type="background",
            )
        )

    worker = threading.Thread(target=_run_background)
    worker.start()
    assert background_started.wait(timeout=1.0)

    started = time.perf_counter()
    dialog_result = router.dispatch(
        BaseMessage(
            message_id="m-62",
            topic="task.dialog",
            source="shell",
            session_id="s-1",
            queue_type="dialog",
        )
    )
    elapsed = time.perf_counter() - started
    release_background.set()
    worker.join()

    assert dialog_result.status == "completed"
    assert dialog_result.result == {"queue": "dialog"}
    assert elapsed < 0.1
    assert background_result["result"].status == "completed"


def test_background_sqlite_conflict_retries_three_times_then_dlq_without_blocking_dialog(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    attempts = {"background": 0, "dialog": 0}
    background_attempted = threading.Event()

    def _fake_execute(message: BaseMessage) -> object:
        if message.queue_type == "background":
            attempts["background"] += 1
            background_attempted.set()
            time.sleep(0.02)
            raise sqlite3.OperationalError("database is locked")
        attempts["dialog"] += 1
        return {"ok": "dialog"}

    router._execute_with_timeout = _fake_execute  # type: ignore[method-assign]
    background_outcome: dict[str, object] = {}

    def _run_background() -> None:
        background_outcome["result"] = router.dispatch(
            BaseMessage(
                message_id="m-63",
                topic="task.bg.locked",
                source="shell",
                session_id="s-1",
                queue_type="background",
                idempotency_key="idem-bg-locked",
            )
        )

    worker = threading.Thread(target=_run_background)
    worker.start()
    assert background_attempted.wait(timeout=1.0)

    started = time.perf_counter()
    dialog_result = router.dispatch(
        BaseMessage(
            message_id="m-64",
            topic="task.dialog.fast",
            source="shell",
            session_id="s-1",
            queue_type="dialog",
        )
    )
    elapsed = time.perf_counter() - started
    worker.join()

    assert dialog_result.status == "completed"
    assert elapsed < 0.1
    assert attempts["background"] == 4
    row = conn.execute(
        "SELECT retry_count, error FROM dead_letter_queue WHERE original_message_id = ?;",
        ("m-63",),
    ).fetchone()
    assert row["retry_count"] == 3
    assert "E_MESSAGE_SQLITE_CONFLICT" in row["error"]
    assert background_outcome["result"].status == "failed"


def test_background_sqlite_conflict_retries_once_then_succeeds(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    attempts = 0

    def _fake_execute(message: BaseMessage) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return {"ok": True}

    router._execute_with_timeout = _fake_execute  # type: ignore[method-assign]
    result = router.dispatch(
        BaseMessage(
            message_id="m-65",
            topic="task.bg.retry",
            source="shell",
            session_id="s-1",
            queue_type="background",
            idempotency_key="idem-bg-retry-success",
        )
    )

    assert result.status == "completed"
    assert attempts == 2
    row = conn.execute(
        "SELECT COUNT(*) FROM dead_letter_queue WHERE original_message_id = ?;",
        ("m-65",),
    ).fetchone()
    assert int(row[0]) == 0


def test_three_background_messages_same_session_run_concurrently(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    active = 0
    peak = 0
    guard = threading.Lock()
    barrier = threading.Barrier(3)

    def _handler(message: BaseMessage) -> object:
        nonlocal active, peak
        barrier.wait()
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return {"message_id": message.message_id}

    router.register("task", _handler)
    threads = [
        threading.Thread(
            target=lambda mid=message_id: router.dispatch(
                BaseMessage(
                    message_id=mid,
                    topic="task.bg.parallel",
                    source="shell",
                    session_id="s-1",
                    queue_type="background",
                )
            )
        )
        for message_id in ("m-66", "m-67", "m-68")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak >= 2


def test_dialog_finishes_before_background_when_background_hits_sqlite_lock(tmp_path: Path) -> None:
    conn = connect(tmp_path / "router.db")
    new_session(conn, "s-1", "default", title=None)
    router = MessageRouter(conn)
    background_attempts = 0
    completions: list[str] = []
    guard = threading.Lock()
    background_started = threading.Event()

    def _fake_execute(message: BaseMessage) -> object:
        nonlocal background_attempts
        if message.queue_type == "background":
            background_attempts += 1
            background_started.set()
            if background_attempts == 1:
                time.sleep(0.02)
                raise sqlite3.OperationalError("database is locked")
            with guard:
                completions.append("background")
            return {"queue": "background"}
        with guard:
            completions.append("dialog")
        return {"queue": "dialog"}

    router._execute_with_timeout = _fake_execute  # type: ignore[method-assign]
    background_result: dict[str, object] = {}

    def _run_background() -> None:
        background_result["result"] = router.dispatch(
            BaseMessage(
                message_id="m-69",
                topic="task.bg.write",
                source="shell",
                session_id="s-1",
                queue_type="background",
                idempotency_key="idem-bg-write",
            )
        )

    worker = threading.Thread(target=_run_background)
    worker.start()
    assert background_started.wait(timeout=1.0)
    dialog_result = router.dispatch(
        BaseMessage(
            message_id="m-70",
            topic="task.dialog.write",
            source="shell",
            session_id="s-1",
            queue_type="dialog",
        )
    )
    worker.join()

    assert dialog_result.status == "completed"
    assert background_result["result"].status == "completed"
    assert completions[0] == "dialog"
    assert "background" in completions
