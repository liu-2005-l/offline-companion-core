"""???????????????????????????????????"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import uuid4

from offline_companion.shared.messages import BaseMessage, MessageDirection
from offline_companion.shell.message_router import ExecutionResult, MessageRouter
from offline_companion.shell.skill_manager.invoker import SkillInvoker

_TASK_TYPES = {"cron", "delay", "long_running", "event"}
_PRIORITY_VALUES = {"low", "normal", "high"}
_EVENT_NOT_IMPLEMENTED = {
    "code": "E_JOB_EVENT_NOT_IMPLEMENTED",
    "message": "event ????????",
}
_SKILL_NOT_ALIVE = {
    "code": "E_JOB_SKILL_NOT_ALIVE",
    "message": "?? Skill ?????????",
}
_HEARTBEAT_TIMEOUT = {
    "code": "E_JOB_HEARTBEAT_TIMEOUT",
    "message": "????????????",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledTask:
    """??????????????????"""

    task_id: str
    skill_name: str
    task_type: str
    status: str
    session_id: str
    queue_type: str
    heartbeat_timeout_sec: int
    delay_until: float | None
    cron_expr: str | None
    payload: dict[str, object]
    error: dict[str, object] | None = None


class CronExpression:
    """????? 5 ?? cron ???????"""

    def __init__(self, expression: str) -> None:
        fields = [field.strip() for field in expression.split() if field.strip()]
        if len(fields) != 5:
            raise ValueError("cron ?????? 5 ???")
        self._expression = expression.strip()
        self._minutes = self._parse_field(fields[0], 0, 59)
        self._hours = self._parse_field(fields[1], 0, 23)
        self._days = self._parse_field(fields[2], 1, 31)
        self._months = self._parse_field(fields[3], 1, 12)
        self._weekdays = self._parse_field(fields[4], 0, 6, allow_7_as_0=True)

    def next_after(self, after_ts: float) -> float:
        """????????????????????"""
        current = datetime.fromtimestamp(after_ts, tz=UTC).replace(second=0, microsecond=0)
        candidate = current + timedelta(minutes=1)
        deadline = candidate + timedelta(days=366)
        while candidate <= deadline:
            if self._matches(candidate):
                return candidate.timestamp()
            candidate += timedelta(minutes=1)
        raise ValueError(f"cron ???????????: {self._expression}")

    def _matches(self, value: datetime) -> bool:
        weekday = (value.weekday() + 1) % 7
        return (
            value.minute in self._minutes
            and value.hour in self._hours
            and value.day in self._days
            and value.month in self._months
            and weekday in self._weekdays
        )

    def _parse_field(
        self,
        field: str,
        minimum: int,
        maximum: int,
        *,
        allow_7_as_0: bool = False,
    ) -> set[int]:
        values: set[int] = set()
        for chunk in field.split(","):
            chunk = chunk.strip()
            if not chunk:
                raise ValueError("cron ??????")
            values.update(self._parse_chunk(chunk, minimum, maximum, allow_7_as_0=allow_7_as_0))
        if not values:
            raise ValueError("cron ??????????")
        return values

    def _parse_chunk(
        self,
        chunk: str,
        minimum: int,
        maximum: int,
        *,
        allow_7_as_0: bool,
    ) -> Iterable[int]:
        step = 1
        base = chunk
        if "/" in chunk:
            base, raw_step = chunk.split("/", 1)
            if not raw_step.isdigit() or int(raw_step) <= 0:
                raise ValueError(f"cron ????: {chunk}")
            step = int(raw_step)
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_raw, end_raw = base.split("-", 1)
            start = self._parse_value(start_raw, minimum, maximum, allow_7_as_0)
            end = self._parse_value(end_raw, minimum, maximum, allow_7_as_0)
            if start > end:
                raise ValueError(f"cron ????: {chunk}")
        else:
            value = self._parse_value(base, minimum, maximum, allow_7_as_0)
            return {value}
        return set(range(start, end + 1, step))

    def _parse_value(self, value: str, minimum: int, maximum: int, allow_7_as_0: bool) -> int:
        if not value.isdigit():
            raise ValueError(f"cron ????: {value!r}")
        parsed = int(value)
        if allow_7_as_0 and parsed == 7:
            parsed = 0
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"cron ??????: {value!r}")
        return parsed


class JobScheduler:
    """????? SQLite ?????????"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        router: MessageRouter,
        invoker: SkillInvoker,
        *,
        poll_interval_sec: float = 0.1,
        execution_workers: int = 4,
    ) -> None:
        self._conn = conn
        self._router = router
        self._invoker = invoker
        self._poll_interval_sec = max(0.05, float(poll_interval_sec))
        self._executor = ThreadPoolExecutor(max_workers=max(1, execution_workers))
        self._stop_event = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._guard = threading.RLock()
        self._running_futures: dict[str, Future[ExecutionResult]] = {}

    def start(self) -> None:
        """????????????"""
        with self._guard:
            if self._loop_thread is not None and self._loop_thread.is_alive():
                return
            self._stop_event.clear()
            self.recover()
            self._loop_thread = threading.Thread(target=self._scheduler_loop, name="job-scheduler", daemon=True)
            self._loop_thread.start()

    def stop(self, *, wait: bool = True) -> None:
        """?????????????????"""
        self._stop_event.set()
        if wait and self._loop_thread is not None:
            self._loop_thread.join(timeout=2.0)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def register_task(
        self,
        skill_name: str,
        task_type: str,
        *,
        session_id: str,
        payload: dict[str, object] | None = None,
        delay_until: float | None = None,
        cron_expr: str | None = None,
        queue_type: str = "background",
        priority: str = "normal",
        heartbeat_timeout_sec: int = 300,
        max_retries: int = 3,
        idempotency_key: str | None = None,
        task_id: str | None = None,
    ) -> ScheduledTask:
        """?????????????? job_tasks?"""
        normalized_task_type = (task_type or "").strip()
        if normalized_task_type not in _TASK_TYPES:
            raise ValueError(f"????????: {task_type!r}")
        if normalized_task_type == "event":
            raise ValueError(f"{_EVENT_NOT_IMPLEMENTED['code']}: {_EVENT_NOT_IMPLEMENTED['message']}")
        normalized_priority = (priority or "normal").strip() or "normal"
        if normalized_priority not in _PRIORITY_VALUES:
            raise ValueError(f"?????????: {priority!r}")
        normalized_queue = (queue_type or "background").strip() or "background"
        if normalized_queue not in {"dialog", "background"}:
            raise ValueError(f"????????: {queue_type!r}")
        if normalized_task_type == "cron":
            if not cron_expr:
                raise ValueError("cron ?????? cron_expr")
            CronExpression(cron_expr)
        if normalized_task_type == "delay" and delay_until is None:
            raise ValueError("delay ?????? delay_until")
        now = self._iso_now()
        persisted_task_id = task_id or str(uuid4())
        self._conn.execute(
            """
            INSERT INTO job_tasks(
                task_id, skill_name, task_type, cron_expr, delay_until, event_condition,
                payload, status, priority, session_id, queue_type, created_at,
                started_at, completed_at, last_heartbeat, heartbeat_timeout_sec,
                retry_count, max_retries, idempotency_key, error
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
            """,
            (
                persisted_task_id,
                skill_name,
                normalized_task_type,
                cron_expr,
                delay_until,
                None,
                json.dumps(payload or {}, ensure_ascii=False),
                "pending",
                normalized_priority,
                session_id,
                normalized_queue,
                now,
                None,
                None,
                None,
                int(max(1, heartbeat_timeout_sec)),
                0,
                int(max(0, max_retries)),
                idempotency_key,
                None,
            ),
        )
        return self.get_task(persisted_task_id)

    def unregister_task(self, task_id: str) -> bool:
        """???????????"""
        cursor = self._conn.execute(
            "DELETE FROM job_tasks WHERE task_id = ? AND status IN ('pending', 'failed', 'completed');",
            (task_id,),
        )
        return int(cursor.rowcount) > 0

    def recover(self) -> None:
        """????????????????"""
        now = self._iso_now()
        self._conn.execute(
            """
            UPDATE job_tasks
            SET status = 'pending',
                started_at = NULL,
                completed_at = NULL,
                last_heartbeat = NULL
            WHERE status IN ('running', 'pending');
            """
        )
        self._conn.execute(
            "UPDATE job_tasks SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL;",
            (now,),
        )

    def get_task(self, task_id: str) -> ScheduledTask:
        """????????????"""
        row = self._conn.execute("SELECT * FROM job_tasks WHERE task_id = ?;", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"?????: {task_id}")
        return self._row_to_task(row)

    def _scheduler_loop(self) -> None:
        """??????????????????????"""
        while not self._stop_event.is_set():
            try:
                self._promote_due_tasks()
                self._refresh_running_heartbeats()
                self._heartbeat_sweeper()
            except (sqlite3.Error, ValueError) as exc:
                logger.warning("JobScheduler 轮询出现可恢复错误: %s", exc)
            except Exception:
                logger.exception("JobScheduler ?????????")
            self._stop_event.wait(self._poll_interval_sec)

    def _promote_due_tasks(self) -> None:
        for row in self._fetch_due_tasks():
            task_id = str(row["task_id"])
            if not self._mark_running(task_id):
                continue
            future = self._executor.submit(self._trigger_task, task_id)
            with self._guard:
                self._running_futures[task_id] = future

    def _fetch_due_tasks(self) -> list[sqlite3.Row]:
        now_ts = time.time()
        rows = self._conn.execute(
            "SELECT * FROM job_tasks WHERE status = 'pending' ORDER BY created_at ASC;"
        ).fetchall()
        due_rows: list[sqlite3.Row] = []
        for row in rows:
            task_type = str(row["task_type"])
            if task_type == "cron":
                if self._cron_due(row, now_ts):
                    due_rows.append(row)
            elif task_type == "delay":
                delay_until = row["delay_until"]
                if delay_until is not None and float(delay_until) <= now_ts:
                    due_rows.append(row)
            elif task_type == "long_running":
                delay_until = row["delay_until"]
                if delay_until is None or float(delay_until) <= now_ts:
                    due_rows.append(row)
        return due_rows

    def _cron_due(self, row: sqlite3.Row, now_ts: float) -> bool:
        cron_expr = row["cron_expr"]
        if not cron_expr:
            return False
        parser = CronExpression(str(cron_expr))
        created_at = self._parse_iso_or_now(row["created_at"])
        last_heartbeat = row["last_heartbeat"]
        baseline = created_at if last_heartbeat is None else self._parse_iso_or_now(last_heartbeat)
        next_run = parser.next_after(baseline)
        return next_run <= now_ts

    def _mark_running(self, task_id: str) -> bool:
        now = self._iso_now()
        cursor = self._conn.execute(
            """
            UPDATE job_tasks
            SET status = 'running', started_at = ?, completed_at = NULL, last_heartbeat = ?
            WHERE task_id = ? AND status = 'pending';
            """,
            (now, now, task_id),
        )
        return int(cursor.rowcount) == 1

    def _trigger_task(self, task_id: str) -> ExecutionResult:
        row = self._conn.execute("SELECT * FROM job_tasks WHERE task_id = ?;", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"?????: {task_id}")
        task = self._row_to_task(row)
        try:
            if not self._check_skill_alive(task.skill_name):
                self._mark_failed(task_id, _SKILL_NOT_ALIVE)
                return self._error_result(task_id, _SKILL_NOT_ALIVE)
            message = self._build_message(task)
            result = self._router.dispatch(message)
            self._finalize_after_dispatch(task, result)
            return result
        finally:
            with self._guard:
                self._running_futures.pop(task_id, None)

    def _build_message(self, task: ScheduledTask) -> BaseMessage:
        timeout = 30.0
        if task.task_type == "long_running":
            timeout = float(task.heartbeat_timeout_sec)
        return BaseMessage(
            message_id=f"job:{task.task_id}",
            topic="skill.invoke",
            source="shell",
            target=task.skill_name,
            session_id=task.session_id,
            idempotency_key=task_idempotency_key(task),
            timeout_sec=timeout,
            queue_type=task.queue_type,
            direction=MessageDirection.INTERNAL,
            payload={
                "task_id": task.task_id,
                "skill_name": task.skill_name,
                **task.payload,
            },
            meta={
                "job_task_type": task.task_type,
                "heartbeat_timeout_sec": task.heartbeat_timeout_sec,
            },
        )

    def _finalize_after_dispatch(self, task: ScheduledTask, result: ExecutionResult) -> None:
        current_status = self._conn.execute(
            "SELECT status FROM job_tasks WHERE task_id = ?;", (task.task_id,)
        ).fetchone()
        if current_status is None:
            return
        if current_status["status"] == "failed":
            return
        if result.status in {"completed", "skipped_duplicate"}:
            if task.task_type == "cron":
                self._reschedule_cron(task.task_id)
            else:
                self._conn.execute(
                    "UPDATE job_tasks SET status = 'completed', completed_at = ?, last_heartbeat = ? WHERE task_id = ?;",
                    (self._iso_now(), self._iso_now(), task.task_id),
                )
            return
        error = result.error or {"code": "E_JOB_DISPATCH_FAILED", "message": "??????"}
        self._mark_failed(task.task_id, error)

    def _reschedule_cron(self, task_id: str) -> None:
        now = self._iso_now()
        self._conn.execute(
            """
            UPDATE job_tasks
            SET status = 'pending', started_at = NULL, completed_at = ?, last_heartbeat = ?
            WHERE task_id = ?;
            """,
            (now, now, task_id),
        )

    def _refresh_running_heartbeats(self) -> None:
        now = self._iso_now()
        finished: list[str] = []
        with self._guard:
            items = list(self._running_futures.items())
        for task_id, future in items:
            if future.done():
                finished.append(task_id)
                continue
            self._conn.execute(
                "UPDATE job_tasks SET last_heartbeat = ? WHERE task_id = ? AND status = 'running';",
                (now, task_id),
            )
        if finished:
            with self._guard:
                for task_id in finished:
                    self._running_futures.pop(task_id, None)

    def _heartbeat_sweeper(self) -> None:
        now_ts = time.time()
        rows = self._conn.execute(
            "SELECT task_id, last_heartbeat, heartbeat_timeout_sec FROM job_tasks WHERE status = 'running';"
        ).fetchall()
        for row in rows:
            last_heartbeat = row["last_heartbeat"]
            if not last_heartbeat:
                continue
            heartbeat_ts = self._parse_iso_or_now(last_heartbeat)
            if now_ts - heartbeat_ts > float(row["heartbeat_timeout_sec"]):
                self._mark_failed(str(row["task_id"]), _HEARTBEAT_TIMEOUT)

    def _mark_failed(self, task_id: str, error: dict[str, object]) -> None:
        self._conn.execute(
            """
            UPDATE job_tasks
            SET status = 'failed', completed_at = ?, last_heartbeat = ?, error = ?
            WHERE task_id = ?;
            """,
            (
                self._iso_now(),
                self._iso_now(),
                json.dumps(error, ensure_ascii=False),
                task_id,
            ),
        )

    def _check_skill_alive(self, skill_name: str) -> bool:
        return self._invoker.is_alive(skill_name)

    def _row_to_task(self, row: sqlite3.Row) -> ScheduledTask:
        return ScheduledTask(
            task_id=str(row["task_id"]),
            skill_name=str(row["skill_name"]),
            task_type=str(row["task_type"]),
            status=str(row["status"]),
            session_id=str(row["session_id"]),
            queue_type=str(row["queue_type"]),
            heartbeat_timeout_sec=int(row["heartbeat_timeout_sec"]),
            delay_until=None if row["delay_until"] is None else float(row["delay_until"]),
            cron_expr=None if row["cron_expr"] is None else str(row["cron_expr"]),
            payload=json.loads(row["payload"] or "{}"),
            error=None if row["error"] is None else json.loads(row["error"]),
        )

    def _error_result(self, task_id: str, error: dict[str, object]) -> ExecutionResult:
        return ExecutionResult(
            message_id=f"job:{task_id}",
            status="failed",
            result=None,
            error=error,
            idempotency_key=None,
            duration_ms=0.0,
        )

    def _parse_iso_or_now(self, value: str | None) -> float:
        if not value:
            return time.time()
        return datetime.fromisoformat(str(value)).timestamp()

    def _iso_now(self) -> str:
        return datetime.now(UTC).isoformat()


def task_idempotency_key(task: ScheduledTask) -> str | None:
    """????????????????"""
    if task.task_type == "cron":
        return None
    return f"job:{task.task_id}"
