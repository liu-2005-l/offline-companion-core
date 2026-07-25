"""state_manager：A2 状态统一读写入口（SQLite + 内存缓存最小版本）。

设计要点：
- 只负责状态存取、事件发布与订阅回调，不承载业务编排。
- 通过 domain 隔离 session / task / system 三类状态。
- 通过 version 提供最小乐观锁能力。
- 所有写入操作写入审计日志，便于排障与合规追踪。
- 通过 role 显式约束读写边界，避免跨域误写。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import time
from typing import Any

from offline_companion.runtime.storage_index.engine import connect
from offline_companion.shared.error_codes import ErrorCode
from offline_companion.shared.errors import ErrorCodeMixin

STATE_DOMAIN_SESSION = "session"
STATE_DOMAIN_TASK = "task"
STATE_DOMAIN_SYSTEM = "system"
STATE_WILDCARD_KEY = "*"
EVENT_NAME_PATTERN = re.compile(r"^[a-z]+(?:_[a-z]+)*(?:\.[a-z]+(?:_[a-z]+)*)+$")

_ALLOWED_DOMAINS = {STATE_DOMAIN_SESSION, STATE_DOMAIN_TASK, STATE_DOMAIN_SYSTEM}
_ALLOWED_ROLES = {
    STATE_DOMAIN_SESSION: {"session"},
    STATE_DOMAIN_TASK: {"task"},
    STATE_DOMAIN_SYSTEM: {"system"},
}

StateChangeCallback = Callable[["StateRecord", "StateRecord | None"], None]


@dataclass(frozen=True)
class StateRecord:
    """摘要：单条状态记录。"""

    domain: str
    key: str
    value: Any
    updated_at: float
    version: int


@dataclass(frozen=True)
class StateEventError:
    """摘要：状态回调异常记录。"""

    domain: str
    key: str
    callback_name: str
    error: str
    occurred_at: float


@dataclass(frozen=True)
class StateAuditRecord:
    """摘要：状态变更审计记录。"""

    domain: str
    key: str
    actor: str
    old_value_json: str | None
    new_value_json: str | None
    version: int
    updated_at: float
    operation: str


@dataclass(frozen=True)
class StateAccessError(ErrorCodeMixin, Exception):
    """摘要：状态域访问被拒绝。"""

    code: str
    domain: str
    key: str
    operation: str
    source: str = "A2"
    recoverable: bool = False
    user_message: str = "请求访问了无权限的状态域。"
    dev_message: str = "state domain access denied"
    error_code: ErrorCode = ErrorCode.E_A2_STATE_ACCESS_DENIED

    def __str__(self) -> str:
        return f"{self.operation} denied for state domain={self.domain!r} key={self.key!r}"


@dataclass(frozen=True)
class StateVersionConflictError(ErrorCodeMixin, Exception):
    """摘要：状态版本冲突。"""

    code: str
    domain: str
    key: str
    expected_version: int
    actual_version: int
    source: str = "A2"
    recoverable: bool = True
    user_message: str = "状态已被更新，请重试。"
    dev_message: str = "state version conflict"
    error_code: ErrorCode = ErrorCode.E_A2_STATE_VERSION_CONFLICT

    def __str__(self) -> str:
        return (
            f"version conflict for state domain={self.domain!r} key={self.key!r} "
            f"expected={self.expected_version} actual={self.actual_version}"
        )


@dataclass(frozen=True)
class StateEventFormatError(ErrorCodeMixin, Exception):
    """摘要：状态事件格式非法。"""

    code: str
    event_name: str
    reason: str
    source: str = "A2"
    recoverable: bool = False
    user_message: str = "事件格式不合法。"
    dev_message: str = "invalid state event format"
    error_code: ErrorCode = ErrorCode.E_A2_STATE_EVENT_INVALID

    def __str__(self) -> str:
        return f"invalid state event {self.event_name!r}: {self.reason}"


@dataclass(frozen=True)
class StateCallbackTypeError(ErrorCodeMixin, TypeError):
    """摘要：状态订阅回调不可调用。"""

    callback_repr: str
    error_code: ErrorCode = ErrorCode.E_A2_STATE_EVENT_INVALID

    def __str__(self) -> str:
        return f"callback must be callable: {self.callback_repr}"


class StateManager:
    """摘要：按 domain/key 统一管理会话、任务、系统与配置状态。"""

    def __init__(self, db_path: str | Path) -> None:
        self._conn = connect(Path(db_path))
        self._lock = RLock()
        self._cache: dict[tuple[str, str], StateRecord] = {}
        self._subscribers: dict[tuple[str, str], list[StateChangeCallback]] = {}
        self._event_errors: list[StateEventError] = []
        self._ensure_schema()
        self._warm_cache()

    def _ensure_schema(self) -> None:
        """摘要：初始化状态表结构与审计表结构。"""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_store (
                    domain TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (domain, key)
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    key TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    old_value_json TEXT,
                    new_value_json TEXT,
                    version INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def _validate_domain(self, domain: str, operation: str, *, key: str = "") -> None:
        """摘要：拒绝非法状态域访问。"""
        if domain not in _ALLOWED_DOMAINS:
            raise StateAccessError(
                code="E_STATE_DOMAIN_DENIED",
                domain=domain,
                key=key,
                operation=operation,
            )

    def _validate_role(self, domain: str, role: str | None, operation: str, *, key: str = "") -> None:
        """摘要：拒绝越权角色访问。"""
        allowed_roles = _ALLOWED_ROLES[domain]
        normalized_role = (role or domain).strip()
        if normalized_role not in allowed_roles:
            raise StateAccessError(
                code="E_STATE_DOMAIN_DENIED",
                domain=domain,
                key=key,
                operation=operation,
                user_message="请求方无权访问该状态域。",
                dev_message=f"role {normalized_role!r} cannot access domain {domain!r}",
            )

    def _warm_cache(self) -> None:
        """摘要：启动时回填内存缓存。"""
        rows = self._conn.execute(
            "SELECT domain, key, value_json, updated_at, version FROM state_store;"
        ).fetchall()
        for domain, key, value_json, updated_at, version in rows:
            self._cache[(domain, key)] = StateRecord(
                domain=domain,
                key=key,
                value=json.loads(value_json),
                updated_at=float(updated_at),
                version=int(version),
            )

    def _validate_event_name(self, event_name: str) -> None:
        """摘要：强制事件名符合 domain.event_type 约定。"""
        if not EVENT_NAME_PATTERN.match(event_name or ""):
            raise StateEventFormatError(
                code="E_STATE_EVENT_INVALID",
                event_name=event_name,
                reason="event name must match domain.event_type",
            )

    def subscribe(self, domain: str, key: str, callback: StateChangeCallback, *, role: str | None = None) -> None:
        """摘要：订阅某个 domain/key 的状态变更。"""
        self._validate_domain(domain, "subscribe", key=key)
        self._validate_role(domain, role, "subscribe", key=key)
        if not callable(callback):
            raise StateCallbackTypeError(repr(callback))
        normalized_key = (key or "").strip() or STATE_WILDCARD_KEY
        with self._lock:
            self._subscribers.setdefault((domain, normalized_key), []).append(callback)

    def unsubscribe(self, domain: str, key: str, callback: StateChangeCallback, *, role: str | None = None) -> bool:
        """摘要：取消订阅某个 domain/key 的状态变更。"""
        self._validate_domain(domain, "unsubscribe", key=key)
        self._validate_role(domain, role, "unsubscribe", key=key)
        normalized_key = (key or "").strip() or STATE_WILDCARD_KEY
        with self._lock:
            callbacks = self._subscribers.get((domain, normalized_key))
            if not callbacks:
                return False
            try:
                callbacks.remove(callback)
            except ValueError:
                return False
            if not callbacks:
                self._subscribers.pop((domain, normalized_key), None)
            return True

    def get_event_errors(self) -> list[StateEventError]:
        """摘要：获取状态回调异常记录。"""
        return list(self._event_errors)

    def clear_event_errors(self) -> None:
        """摘要：清空状态回调异常记录。"""
        self._event_errors.clear()

    def _record_event_error(self, domain: str, key: str, callback: StateChangeCallback, error: Exception) -> None:
        """摘要：记录订阅回调异常，不中断主写入流程。"""
        self._event_errors.append(
            StateEventError(
                domain=domain,
                key=key,
                callback_name=getattr(callback, "__name__", callback.__class__.__name__),
                error=str(error),
                occurred_at=time(),
            )
        )

    def _record_audit(self, domain: str, key: str, actor: str, operation: str, old_value: Any, new_value: Any, version: int, updated_at: float) -> None:
        """摘要：记录状态变更审计日志。"""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO state_audit_log(domain, key, actor, operation, old_value_json, new_value_json, version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    domain,
                    key,
                    actor,
                    operation,
                    None if old_value is None else json.dumps(old_value, ensure_ascii=False, sort_keys=True),
                    None if new_value is None else json.dumps(new_value, ensure_ascii=False, sort_keys=True),
                    version,
                    updated_at,
                ),
            )

    def _notify(self, new_record: StateRecord, old_record: StateRecord | None) -> None:
        """摘要：同步通知订阅者，单个回调失败不影响其他回调。"""
        callbacks = list(self._subscribers.get((new_record.domain, new_record.key), []))
        callbacks.extend(self._subscribers.get((new_record.domain, STATE_WILDCARD_KEY), []))
        for callback in callbacks:
            try:
                callback(new_record, old_record)
            except Exception as exc:
                self._record_event_error(new_record.domain, new_record.key, callback, exc)
                continue

    def publish_event(self, domain: str, event_name: str, data: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
        """摘要：发布规范化事件，供上层业务模块订阅。"""
        self._validate_domain(domain, "publish_event")
        self._validate_event_name(event_name)
        payload = {
            "trace_id": str(data.get("trace_id", "")).strip(),
            "source": (source or str(data.get("source", "")).strip() or domain).strip(),
            "version": int(data.get("version", 0)),
            "timestamp": int(data.get("timestamp", time() * 1000)),
            "data": dict(data.get("data", {})),
        }
        if not payload["trace_id"]:
            raise StateEventFormatError(
                code="E_STATE_EVENT_INVALID",
                event_name=event_name,
                reason="missing trace_id",
            )
        if not payload["source"]:
            raise StateEventFormatError(
                code="E_STATE_EVENT_INVALID",
                event_name=event_name,
                reason="missing source",
            )
        if payload["version"] < 0:
            raise StateEventFormatError(
                code="E_STATE_EVENT_INVALID",
                event_name=event_name,
                reason="invalid version",
            )
        event_key = f"event:{event_name}"
        current_event = self.get_record(domain, event_key)
        current_version = 0 if current_event is None else current_event.version
        record = self.set(domain, event_key, {"event_name": event_name, **payload})
        if record.version <= current_version:
            raise StateVersionConflictError(
                code="E_STATE_VERSION_CONFLICT",
                domain=domain,
                key=event_key,
                expected_version=current_version + 1,
                actual_version=record.version,
            )
        return {"event_name": event_name, **payload}

    def get(self, domain: str, key: str, default: Any = None, *, role: str | None = None) -> Any:
        """摘要：读取状态值。"""
        self._validate_domain(domain, "get", key=key)
        self._validate_role(domain, role, "get", key=key)
        record = self._cache.get((domain, key))
        if record is not None:
            return record.value
        row = self._conn.execute(
            "SELECT value_json, updated_at, version FROM state_store WHERE domain = ? AND key = ?;",
            (domain, key),
        ).fetchone()
        if not row:
            return default
        value = json.loads(row[0])
        record = StateRecord(domain=domain, key=key, value=value, updated_at=float(row[1]), version=int(row[2]))
        self._cache[(domain, key)] = record
        return value

    def get_record(self, domain: str, key: str, *, role: str | None = None) -> StateRecord | None:
        """摘要：读取包含版本号的状态记录。"""
        self._validate_domain(domain, "get_record", key=key)
        self._validate_role(domain, role, "get_record", key=key)
        record = self._cache.get((domain, key))
        if record is not None:
            return record
        row = self._conn.execute(
            "SELECT value_json, updated_at, version FROM state_store WHERE domain = ? AND key = ?;",
            (domain, key),
        ).fetchone()
        if not row:
            return None
        record = StateRecord(domain=domain, key=key, value=json.loads(row[0]), updated_at=float(row[1]), version=int(row[2]))
        self._cache[(domain, key)] = record
        return record

    def set(self, domain: str, key: str, value: Any, *, role: str | None = None, actor: str | None = None) -> StateRecord:
        """摘要：写入状态并递增版本号。"""
        self._validate_domain(domain, "set", key=key)
        self._validate_role(domain, role, "set", key=key)
        updated_at = time()
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        old_record = self._cache.get((domain, key))
        new_version = 1 if old_record is None else old_record.version + 1
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO state_store(domain, key, value_json, updated_at, version)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(domain, key)
                DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at, version = excluded.version;
                """,
                (domain, key, payload, updated_at, new_version),
            )
        record = StateRecord(domain=domain, key=key, value=value, updated_at=updated_at, version=new_version)
        self._cache[(domain, key)] = record
        self._record_audit(
            domain,
            key,
            actor=(actor or role or domain),
            operation="set",
            old_value=None if old_record is None else old_record.value,
            new_value=value,
            version=new_version,
            updated_at=updated_at,
        )
        self._notify(record, old_record)
        return record

    def set_if_version(self, domain: str, key: str, value: Any, expected_version: int, *, role: str | None = None, actor: str | None = None) -> StateRecord:
        """摘要：基于预期版本写入状态，版本不匹配则拒绝。"""
        self._validate_domain(domain, "set_if_version", key=key)
        self._validate_role(domain, role, "set_if_version", key=key)
        current = self.get_record(domain, key, role=role)
        current_version = 0 if current is None else current.version
        if current_version != expected_version:
            raise StateVersionConflictError(
                code="E_STATE_VERSION_CONFLICT",
                domain=domain,
                key=key,
                expected_version=expected_version,
                actual_version=current_version,
            )
        return self.set(domain, key, value, role=role, actor=actor)

    def set_with_retry(self, domain: str, key: str, value: Any, max_retries: int = 3, *, role: str | None = None, actor: str | None = None) -> StateRecord:
        """摘要：在版本冲突时自动重试写入。"""
        self._validate_domain(domain, "set_with_retry", key=key)
        self._validate_role(domain, role, "set_with_retry", key=key)
        retries = max(0, int(max_retries))
        last_error: Exception | None = None
        for _ in range(retries + 1):
            current = self.get_record(domain, key, role=role)
            expected_version = 0 if current is None else current.version
            try:
                return self.set_if_version(domain, key, value, expected_version=expected_version, role=role, actor=actor)
            except StateVersionConflictError as exc:
                last_error = exc
                continue
        assert last_error is not None
        raise last_error

    def delete(self, domain: str, key: str, *, role: str | None = None, actor: str | None = None) -> None:
        """摘要：删除状态并通知订阅者。"""
        self._validate_domain(domain, "delete", key=key)
        self._validate_role(domain, role, "delete", key=key)
        old_record = self._cache.get((domain, key))
        updated_at = time()
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM state_store WHERE domain = ? AND key = ?;",
                (domain, key),
            )
        self._cache.pop((domain, key), None)
        if old_record is not None:
            self._record_audit(
                domain,
                key,
                actor=(actor or role or domain),
                operation="delete",
                old_value=old_record.value,
                new_value=None,
                version=old_record.version + 1,
                updated_at=updated_at,
            )
            self._notify(StateRecord(domain=domain, key=key, value=None, updated_at=updated_at, version=old_record.version + 1), old_record)

    def get_session_state(self, key: str, default: Any = None, *, role: str | None = None) -> Any:
        """摘要：读取会话域状态。"""
        return self.get(STATE_DOMAIN_SESSION, key, default, role=role)

    def set_session_state(self, key: str, value: Any, *, role: str | None = None, actor: str | None = None) -> StateRecord:
        """摘要：写入会话域状态。"""
        return self.set(STATE_DOMAIN_SESSION, key, value, role=role, actor=actor)

    def get_task_state(self, key: str, default: Any = None, *, role: str | None = None) -> Any:
        """摘要：读取任务域状态。"""
        return self.get(STATE_DOMAIN_TASK, key, default, role=role)

    def set_task_state(self, key: str, value: Any, *, role: str | None = None, actor: str | None = None) -> StateRecord:
        """摘要：写入任务域状态。"""
        return self.set(STATE_DOMAIN_TASK, key, value, role=role, actor=actor)

    def set_route_state(self, plan_id: str, value: dict[str, Any], *, actor: str | None = None) -> StateRecord:
        """摘要：写入计划路由决策快照。"""
        return self.set_task_state(f"plan.{plan_id}.route_decision", value, actor=actor)

    def get_route_state(self, plan_id: str, default: Any = None) -> Any:
        """摘要：读取计划路由决策快照。"""
        return self.get_task_state(f"plan.{plan_id}.route_decision", default)

    def get_system_state(self, key: str, default: Any = None, *, role: str | None = None) -> Any:
        """摘要：读取系统域状态。"""
        return self.get(STATE_DOMAIN_SYSTEM, key, default, role=role)

    def set_system_state(self, key: str, value: Any, *, role: str | None = None, actor: str | None = None) -> StateRecord:
        """摘要：写入系统域状态。"""
        return self.set(STATE_DOMAIN_SYSTEM, key, value, role=role, actor=actor)

    def trigger_idle_think(self, *, role: str | None = None, actor: str | None = None) -> StateRecord:
        """触发一次空闲思考信号。"""
        return self.set_system_state("idle_think_requested", True, role=role, actor=actor)
