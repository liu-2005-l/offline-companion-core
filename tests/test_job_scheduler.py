from __future__ import annotations

import time
from pathlib import Path

import pytest

from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shell.job_scheduler import CronExpression, JobScheduler
from offline_companion.shell.message_router import MessageRouter


class StubInvoker:
    def __init__(self, *, alive: bool = True) -> None:
        self.alive = alive
        self.queries: list[str] = []

    def is_alive(self, name: str) -> bool:
        self.queries.append(name)
        return self.alive


def _build_router(conn):
    router = MessageRouter(conn)
    return router


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('??????')


def test_cron_expression_parses_next_run() -> None:
    parser = CronExpression('*/5 * * * *')
    base = 1_700_000_000.0
    assert parser.next_after(base) > base


def test_register_delay_task_and_trigger_dispatch(tmp_path: Path) -> None:
    conn = connect(tmp_path / 'scheduler.db')
    new_session(conn, 's-1', 'default', title=None)
    router = _build_router(conn)
    events: list[dict[str, object]] = []
    router.register('skill', lambda message: events.append({'payload': message.payload, 'timeout': message.timeout_sec}) or {'ok': True})
    scheduler = JobScheduler(conn, router, StubInvoker(), poll_interval_sec=0.05)
    scheduler.start()
    try:
        task = scheduler.register_task(
            'mock-skill',
            'delay',
            session_id='s-1',
            delay_until=time.time() + 0.05,
            payload={'value': 42},
        )
        _wait_until(
            lambda: len(events) == 1
            and conn.execute(
                'SELECT status FROM job_tasks WHERE task_id = ?;',
                (task.task_id,),
            ).fetchone()['status'] == 'completed'
        )
        row = conn.execute('SELECT status FROM job_tasks WHERE task_id = ?;', (task.task_id,)).fetchone()
        assert row['status'] == 'completed'
        assert events[0]['payload']['value'] == 42
        assert events[0]['timeout'] == 30.0
    finally:
        scheduler.stop()


def test_long_running_uses_heartbeat_timeout_as_dispatch_timeout(tmp_path: Path) -> None:
    conn = connect(tmp_path / 'scheduler.db')
    new_session(conn, 's-1', 'default', title=None)
    router = _build_router(conn)
    seen: list[float] = []
    router.register('skill', lambda message: seen.append(message.timeout_sec) or {'ok': True})
    scheduler = JobScheduler(conn, router, StubInvoker(), poll_interval_sec=0.05)
    scheduler.start()
    try:
        scheduler.register_task(
            'mock-skill',
            'long_running',
            session_id='s-1',
            heartbeat_timeout_sec=7,
            payload={'kind': 'long'},
        )
        _wait_until(lambda: len(seen) == 1)
        assert seen[0] == 7.0
    finally:
        scheduler.stop()


def test_skill_not_alive_marks_task_failed(tmp_path: Path) -> None:
    conn = connect(tmp_path / 'scheduler.db')
    new_session(conn, 's-1', 'default', title=None)
    router = _build_router(conn)
    router.register('skill', lambda message: {'ok': True})
    invoker = StubInvoker(alive=False)
    scheduler = JobScheduler(conn, router, invoker, poll_interval_sec=0.05)
    scheduler.start()
    try:
        task = scheduler.register_task('offline-skill', 'delay', session_id='s-1', delay_until=time.time())
        _wait_until(lambda: conn.execute('SELECT status FROM job_tasks WHERE task_id = ?;', (task.task_id,)).fetchone()['status'] == 'failed')
        assert invoker.queries == ['offline-skill']
        row = conn.execute('SELECT error FROM job_tasks WHERE task_id = ?;', (task.task_id,)).fetchone()
        assert row['error'] is not None
        assert 'E_JOB_SKILL_NOT_ALIVE' in row['error']
    finally:
        scheduler.stop()


def test_recover_resets_running_task_to_pending(tmp_path: Path) -> None:
    conn = connect(tmp_path / 'scheduler.db')
    new_session(conn, 's-1', 'default', title=None)
    router = _build_router(conn)
    scheduler = JobScheduler(conn, router, StubInvoker(), poll_interval_sec=0.05)
    task = scheduler.register_task('mock-skill', 'delay', session_id='s-1', delay_until=time.time() + 60)
    conn.execute(
        "UPDATE job_tasks SET status = 'running', started_at = ?, last_heartbeat = ? WHERE task_id = ?;",
        ('2026-07-26T00:00:00+00:00', '2026-07-26T00:00:00+00:00', task.task_id),
    )

    scheduler.recover()

    row = conn.execute('SELECT status, started_at, last_heartbeat FROM job_tasks WHERE task_id = ?;', (task.task_id,)).fetchone()
    assert row['status'] == 'pending'
    assert row['started_at'] is None
    assert row['last_heartbeat'] is None


def test_heartbeat_sweeper_marks_stale_running_task_failed(tmp_path: Path) -> None:
    conn = connect(tmp_path / 'scheduler.db')
    new_session(conn, 's-1', 'default', title=None)
    router = _build_router(conn)
    scheduler = JobScheduler(conn, router, StubInvoker(), poll_interval_sec=0.05)
    task = scheduler.register_task('mock-skill', 'long_running', session_id='s-1', heartbeat_timeout_sec=1)
    stale_ts = '2026-07-26T00:00:00+00:00'
    conn.execute(
        "UPDATE job_tasks SET status = 'running', last_heartbeat = ? WHERE task_id = ?;",
        (stale_ts, task.task_id),
    )

    scheduler._heartbeat_sweeper()

    row = conn.execute('SELECT status, error FROM job_tasks WHERE task_id = ?;', (task.task_id,)).fetchone()
    assert row['status'] == 'failed'
    assert row['error'] is not None
    assert 'E_JOB_HEARTBEAT_TIMEOUT' in row['error']


def test_cron_task_triggers_when_due(tmp_path: Path) -> None:
    conn = connect(tmp_path / 'scheduler.db')
    new_session(conn, 's-1', 'default', title=None)
    router = _build_router(conn)
    calls: list[str] = []
    router.register('skill', lambda message: calls.append(message.message_id) or {'ok': True})
    scheduler = JobScheduler(conn, router, StubInvoker(), poll_interval_sec=0.05)
    scheduler.start()
    try:
        task = scheduler.register_task('mock-skill', 'cron', session_id='s-1', cron_expr='* * * * *')
        old_created = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(time.time() - 120))
        conn.execute('UPDATE job_tasks SET created_at = ? WHERE task_id = ?;', (old_created, task.task_id))
        _wait_until(lambda: len(calls) >= 1)
        row = conn.execute('SELECT status FROM job_tasks WHERE task_id = ?;', (task.task_id,)).fetchone()
        assert row['status'] == 'pending'
    finally:
        scheduler.stop()


def test_cron_task_does_not_spin_within_same_minute(tmp_path: Path) -> None:
    conn = connect(tmp_path / 'scheduler.db')
    new_session(conn, 's-1', 'default', title=None)
    router = _build_router(conn)
    calls: list[float] = []
    router.register('skill', lambda message: calls.append(time.time()) or {'ok': True})
    scheduler = JobScheduler(conn, router, StubInvoker(), poll_interval_sec=0.05)
    task = scheduler.register_task('mock-skill', 'cron', session_id='s-1', cron_expr='* * * * *')
    now = time.time()
    baseline = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(now - 120))
    conn.execute('UPDATE job_tasks SET created_at = ? WHERE task_id = ?;', (baseline, task.task_id))

    scheduler._promote_due_tasks()
    _wait_until(lambda: len(calls) == 1)
    row = conn.execute('SELECT last_heartbeat FROM job_tasks WHERE task_id = ?;', (task.task_id,)).fetchone()

    assert row['last_heartbeat'] is not None
    assert scheduler._cron_due(conn.execute('SELECT * FROM job_tasks WHERE task_id = ?;', (task.task_id,)).fetchone(), time.time()) is False


def test_register_event_task_returns_not_implemented(tmp_path: Path) -> None:
    conn = connect(tmp_path / 'scheduler.db')
    new_session(conn, 's-1', 'default', title=None)
    scheduler = JobScheduler(conn, _build_router(conn), StubInvoker(), poll_interval_sec=0.05)

    with pytest.raises(ValueError, match='E_JOB_EVENT_NOT_IMPLEMENTED'):
        scheduler.register_task('mock-skill', 'event', session_id='s-1')
