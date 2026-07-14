"""state_manager：A2 状态统一读写入口（SQLite + 内存缓存最小版本）。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import time
from typing import Any

from offline_companion.runtime.storage_index.engine import connect

STATE_DOMAIN_SESSION = "session"
STATE_DOMAIN_TASK = "task"
STATE_DOMAIN_SYSTEM = "system"

StateChangeCallback = Callable[["StateRecord", "StateRecord | None"], None]


@dataclass(frozen=True)
class StateRecord:
    """摘要：单条状态记录。"""

    domain: str
    key: str
    value: Any
    updated_at: float


class StateManager:
    """摘要：按 domain/key 统一管理会话、任务、系统与配置状态。"""

    def __init__(self, db_path: str | Path) -> None:
        self._conn = connect(Path(db_path))
        self._lock = RLock()
        self._cache: dict[tuple[str, str], StateRecord] = {}
        self._subscribers: dict[tuple[str, str], list[StateChangeCallback]] = {}
        self._ensure_schema()
        self._warm_cache()

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_store (
                    domain TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (domain, key)
                );
                """
            )

    def _warm_cache(self) -> None:
        rows = self._conn.execute(
            "SELECT domain, key, value_json, updated_at FROM state_store;"
        ).fetchall()
        for domain, key, value_json, updated_at in rows:
            self._cache[(domain, key)] = StateRecord(
                domain=domain,
                key=key,
                value=json.loads(value_json),
                updated_at=float(updated_at),
            )

    def subscribe(self, domain: str, key: str, callback: StateChangeCallback) -> None:
        """摘要：订阅某个 domain/key 的状态变更。"""
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            self._subscribers.setdefault((domain, key), []).append(callback)

    def _notify(self, new_record: StateRecord, old_record: StateRecord | None) -> None:
        callbacks = list(self._subscribers.get((new_record.domain, new_record.key), []))
        for callback in callbacks:
            try:
                callback(new_record, old_record)
            except Exception:
                continue

    def get(self, domain: str, key: str, default: Any = None) -> Any:
        record = self._cache.get((domain, key))
        if record is not None:
            return record.value
        row = self._conn.execute(
            "SELECT value_json, updated_at FROM state_store WHERE domain = ? AND key = ?;",
            (domain, key),
        ).fetchone()
        if not row:
            return default
        value = json.loads(row[0])
        record = StateRecord(domain=domain, key=key, value=value, updated_at=float(row[1]))
        self._cache[(domain, key)] = record
        return value

    def set(self, domain: str, key: str, value: Any) -> StateRecord:
        updated_at = time()
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        old_record = self._cache.get((domain, key))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO state_store(domain, key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(domain, key)
                DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at;
                """,
                (domain, key, payload, updated_at),
            )
        record = StateRecord(domain=domain, key=key, value=value, updated_at=updated_at)
        self._cache[(domain, key)] = record
        self._notify(record, old_record)
        return record

    def delete(self, domain: str, key: str) -> None:
        old_record = self._cache.get((domain, key))
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM state_store WHERE domain = ? AND key = ?;",
                (domain, key),
            )
        self._cache.pop((domain, key), None)
        if old_record is not None:
            self._notify(StateRecord(domain=domain, key=key, value=None, updated_at=time()), old_record)

    def get_session_state(self, key: str, default: Any = None) -> Any:
        """摘要：读取会话域状态。"""
        return self.get(STATE_DOMAIN_SESSION, key, default)

    def set_session_state(self, key: str, value: Any) -> StateRecord:
        """摘要：写入会话域状态。"""
        return self.set(STATE_DOMAIN_SESSION, key, value)

    def get_task_state(self, key: str, default: Any = None) -> Any:
        """摘要：读取任务域状态。"""
        return self.get(STATE_DOMAIN_TASK, key, default)

    def set_task_state(self, key: str, value: Any) -> StateRecord:
        """摘要：写入任务域状态。"""
        return self.set(STATE_DOMAIN_TASK, key, value)

    def get_system_state(self, key: str, default: Any = None) -> Any:
        """摘要：读取系统域状态。"""
        return self.get(STATE_DOMAIN_SYSTEM, key, default)

    def set_system_state(self, key: str, value: Any) -> StateRecord:
        """摘要：写入系统域状态。"""
        return self.set(STATE_DOMAIN_SYSTEM, key, value)
