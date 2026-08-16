"""???A/B/C ???????????????"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from time import perf_counter
from uuid import uuid4

from offline_companion.shared.messages import BaseMessage, MessageLayer
from offline_companion.shell.auto_router import AutoRoutingAdapter

MessageHandler = Callable[[BaseMessage], object]


@dataclass(frozen=True)
class ExecutionResult:
    """??????????"""

    message_id: str
    status: str
    result: object | None
    error: dict[str, object] | None
    idempotency_key: str | None
    duration_ms: float


class MessageRouter:
    """???? topic ???????????? dispatch ???"""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._handlers: dict[str, MessageHandler] = {}
        self._wildcard_handler: MessageHandler | None = None
        self._auto_router: AutoRoutingAdapter | None = None
        self._conn = conn
        self._session_locks: dict[str, RLock] = {}
        self._session_locks_guard = RLock()

    def register(self, namespace: str, handler: MessageHandler) -> None:
        key = (namespace or "").strip()
        if not key:
            raise ValueError("namespace ????")
        if "." in key or key == "*":
            raise ValueError("namespace ?????????????????")
        self._handlers[key] = handler

    def register_wildcard(self, handler: MessageHandler) -> None:
        """?????????????????"""
        self._wildcard_handler = handler

    def register_auto_router(self, auto_router: AutoRoutingAdapter) -> None:
        """?????????????"""
        self._auto_router = auto_router

    def close(self) -> None:
        """摘要：清理路由注册表与会话锁，供插件生命周期卸载使用。"""
        self._handlers.clear()
        self._wildcard_handler = None
        self._auto_router = None
        with self._session_locks_guard:
            self._session_locks.clear()

    def route(self, message: BaseMessage) -> object:
        namespace = message.namespace().strip()
        if not namespace:
            raise ValueError("?? topic ????")
        if message.source != MessageLayer.SHELL.value and namespace == "shell":
            raise ValueError("shell ????????? shell ???")

        if self._auto_router is not None:
            decision = self._auto_router.route(message)
            message = message.with_meta(auto_route=decision.mode.value, auto_route_reason=decision.reason)

        handler = self._handlers.get(namespace)
        if handler is None:
            handler = self._wildcard_handler
        if handler is None:
            raise KeyError(f"????????: {message.topic!r}")
        return handler(message)

    def dispatch(self, message: BaseMessage) -> ExecutionResult:
        """???????????????????????"""
        started = perf_counter()
        existing = self._check_idempotency(message)
        if existing is not None:
            return existing

        lock = self._session_lock(message.session_id, message.queue_type)
        max_conflict_retries = 3 if message.queue_type == "background" else 0
        max_handler_retries = 1
        with lock:
            conflict_retries = 0
            handler_retries = 0
            while True:
                existing = self._check_idempotency(message)
                if existing is not None:
                    return existing
                self._record_execution(message, "executing")
                try:
                    result = self._execute_with_timeout(message)
                except sqlite3.OperationalError as exc:
                    if self._should_retry_background(message, exc, conflict_retries, max_conflict_retries):
                        conflict_retries += 1
                        continue
                    error = self._error_payload("E_MESSAGE_SQLITE_CONFLICT", str(exc))
                    self._record_execution(message, "failed", error=error)
                    self._send_to_dlq(message, error, retry_count=conflict_retries)
                    return self._error_result(message, "failed", error, started)
                except TimeoutError as exc:
                    if self._should_retry_handler(handler_retries, max_handler_retries):
                        handler_retries += 1
                        completed = self._check_completed_idempotency(message)
                        if completed is not None:
                            return completed
                        continue
                    error = self._error_payload("E_MESSAGE_TIMEOUT", str(exc))
                    self._record_execution(message, "failed", error=error)
                    self._send_to_dlq(message, error, retry_count=handler_retries)
                    return self._error_result(message, "timeout", error, started)
                except Exception as exc:
                    if self._should_retry_handler(handler_retries, max_handler_retries):
                        handler_retries += 1
                        completed = self._check_completed_idempotency(message)
                        if completed is not None:
                            return completed
                        continue
                    error = self._error_payload("E_MESSAGE_HANDLER_FAILED", str(exc))
                    self._record_execution(message, "failed", error=error)
                    self._send_to_dlq(message, error, retry_count=handler_retries)
                    return self._error_result(message, "failed", error, started)

                self._record_execution(message, "completed", result=result)
                return ExecutionResult(
                    message_id=message.message_id,
                    status="completed",
                    result=result,
                    error=None,
                    idempotency_key=message.idempotency_key,
                    duration_ms=(perf_counter() - started) * 1000.0,
                )

        error = self._error_payload("E_MESSAGE_ROUTER_UNREACHABLE", "message dispatch exhausted")
        self._send_to_dlq(message, error, retry_count=0)
        return self._error_result(message, "failed", error, started)

    def _check_idempotency(self, message: BaseMessage) -> ExecutionResult | None:
        if self._conn is None or not message.idempotency_key:
            return None
        row = self._conn.execute(
            """
            SELECT status, result, error
            FROM message_execution_records
            WHERE idempotency_key = ?;
            """,
            (message.idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "completed":
            return None
        result = json.loads(row["result"]) if row["result"] else None
        error = json.loads(row["error"]) if row["error"] else None
        return ExecutionResult(
            message_id=message.message_id,
            status="skipped_duplicate",
            result=result,
            error=error,
            idempotency_key=message.idempotency_key,
            duration_ms=0.0,
        )

    def _check_completed_idempotency(self, message: BaseMessage) -> ExecutionResult | None:
        existing = self._check_idempotency(message)
        if existing is None or existing.status != "skipped_duplicate":
            return None
        return existing

    def _session_lock(self, session_id: str, queue_type: str) -> RLock:
        if queue_type != "dialog":
            return RLock()
        normalized = session_id or "__global__"
        with self._session_locks_guard:
            lock = self._session_locks.get(normalized)
            if lock is None:
                lock = RLock()
                self._session_locks[normalized] = lock
            return lock

    def _execute_with_timeout(self, message: BaseMessage) -> object:
        timeout = message.timeout_sec or 30.0
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self.route, message)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            raise TimeoutError(f"message {message.message_id} timeout after {timeout:.1f}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _record_execution(
        self,
        message: BaseMessage,
        status: str,
        *,
        result: object | None = None,
        error: dict[str, object] | None = None,
    ) -> None:
        if self._conn is None or not message.idempotency_key:
            return
        now = self._iso_now()
        self._conn.execute(
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
                message.idempotency_key,
                message.message_id,
                message.session_id,
                message.namespace(),
                status,
                None if result is None else json.dumps(result, ensure_ascii=False),
                None if error is None else json.dumps(error, ensure_ascii=False),
                now,
                now if status != "executing" else None,
            ),
        )

    def _send_to_dlq(self, message: BaseMessage, error: dict[str, object], *, retry_count: int) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            """
            INSERT INTO dead_letter_queue(
                dlq_id, original_message_id, session_id, queue_type,
                handler_namespace, original_payload, error, retry_count, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?);
            """,
            (
                str(uuid4()),
                message.message_id,
                message.session_id,
                message.queue_type,
                message.namespace(),
                json.dumps(
                    {
                        "topic": message.topic,
                        "payload": message.payload,
                        "meta": message.meta,
                        "idempotency_key": message.idempotency_key,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(error, ensure_ascii=False),
                retry_count,
                self._iso_now(),
            ),
        )

    def _should_retry_background(
        self,
        message: BaseMessage,
        error: sqlite3.OperationalError,
        conflict_retries: int,
        max_conflict_retries: int,
    ) -> bool:
        return (
            message.queue_type == "background"
            and conflict_retries < max_conflict_retries
            and "locked" in str(error).lower()
        )

    def _should_retry_handler(
        self,
        handler_retries: int,
        max_handler_retries: int,
    ) -> bool:
        return handler_retries < max_handler_retries

    def _error_result(
        self,
        message: BaseMessage,
        status: str,
        error: dict[str, object],
        started: float,
    ) -> ExecutionResult:
        return ExecutionResult(
            message_id=message.message_id,
            status=status,
            result=None,
            error=error,
            idempotency_key=message.idempotency_key,
            duration_ms=(perf_counter() - started) * 1000.0,
        )

    def _error_payload(self, code: str, message: str) -> dict[str, object]:
        return {"code": code, "message": message}

    def _iso_now(self) -> str:
        return datetime.now(UTC).isoformat()
