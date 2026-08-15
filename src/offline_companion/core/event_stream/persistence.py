"""DomainEvent 的 SQLite write-behind 持久化适配器。"""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import DomainEvent

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS domain_events (
    event_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    schema_version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(stream_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_domain_events_stream_seq
    ON domain_events(stream_id, seq);
CREATE INDEX IF NOT EXISTS idx_domain_events_type_timestamp
    ON domain_events(event_type, timestamp);
"""


class EventPersistence:
    """异步批量写入并从 SQLite 恢复领域事件。

    参数：
        db_path: SQLite 文件路径，也支持 `:memory:` 测试数据库。
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        self._conn_lock = threading.Lock()
        self._write_queue: queue.Queue[DomainEvent | None] = queue.Queue()
        self._closed = False
        self._shutdown_lock = threading.Lock()
        self._writer_thread = threading.Thread(
            target=self._write_loop,
            name="domain-event-writer",
            daemon=True,
        )
        self._writer_thread.start()
        self.recovery_mode = False

    def enqueue(self, event: DomainEvent) -> None:
        """将事件放入 write-behind 队列，不等待磁盘写入。"""
        with self._shutdown_lock:
            if self._closed:
                logger.warning("事件持久化已关闭，忽略事件 %s", event.event_id)
                return
            self._write_queue.put(event)

    def flush(self, timeout: float | None = None) -> None:
        """等待当前队列中的事件完成一次写入。"""
        if timeout is None:
            self._write_queue.join()
            return
        completed = threading.Event()

        def wait_for_queue() -> None:
            self._write_queue.join()
            completed.set()

        waiter = threading.Thread(target=wait_for_queue, daemon=True)
        waiter.start()
        if not completed.wait(timeout):
            raise TimeoutError("等待事件持久化写入超时")

    def _write_loop(self) -> None:
        """批量消费队列；单次写入失败不影响 append 调用方。"""
        while True:
            item = self._write_queue.get()
            if item is None:
                self._write_queue.task_done()
                return
            batch = [item]
            try:
                while True:
                    batch_item = self._write_queue.get_nowait()
                    if batch_item is None:
                        self._write_queue.task_done()
                        self._flush_batch(batch)
                        for _ in batch:
                            self._write_queue.task_done()
                        return
                    batch.append(batch_item)
            except queue.Empty:
                pass
            try:
                self._flush_batch(batch)
            except Exception:
                logger.exception("事件批量写入失败")
            finally:
                for _ in batch:
                    self._write_queue.task_done()

    def _flush_batch(self, events: list[DomainEvent]) -> None:
        """批量写入事件，失败时逐条重试。"""
        rows = [
            (
                event.event_id,
                event.stream_id,
                event.seq,
                event.event_type,
                event.timestamp,
                event.schema_version,
                json.dumps(event.payload, ensure_ascii=False),
            )
            for event in events
        ]
        with self._conn_lock:
            try:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO domain_events "
                    "(event_id, stream_id, seq, event_type, timestamp, schema_version, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                self._conn.commit()
                return
            except Exception:
                self._conn.rollback()
                logger.exception("事件批量写入失败，开始逐条重试")

            for row in rows:
                try:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO domain_events "
                        "(event_id, stream_id, seq, event_type, timestamp, schema_version, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    logger.exception("事件 %s 持久化失败", row[0])

    def load_stream(self, stream_id: str, from_seq: int = 0) -> list[DomainEvent]:
        """按序加载事件，并在发现 seq 缺口时截断到连续前缀。"""
        from .types import DomainEvent

        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT event_id, stream_id, seq, event_type, timestamp, schema_version, payload "
                "FROM domain_events WHERE stream_id = ? AND seq >= ? ORDER BY seq",
                (stream_id, from_seq),
            ).fetchall()
        events: list[DomainEvent] = []
        expected_seq = max(0, from_seq)
        for row in rows:
            if int(row["seq"]) != expected_seq:
                self.recovery_mode = True
                logger.warning(
                    "事件流 %s seq 不连续，期望 %s，实际 %s；截断后续事件",
                    stream_id,
                    expected_seq,
                    row["seq"],
                )
                break
            events.append(
                DomainEvent(
                    event_id=row["event_id"],
                    stream_id=row["stream_id"],
                    seq=int(row["seq"]),
                    event_type=row["event_type"],
                    timestamp=float(row["timestamp"]),
                    schema_version=int(row["schema_version"]),
                    payload=json.loads(row["payload"]),
                )
            )
            expected_seq += 1
        return events

    def load_all_streams(self) -> dict[str, list[DomainEvent]]:
        """加载所有事件流及其连续事件前缀。"""
        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT DISTINCT stream_id FROM domain_events ORDER BY stream_id"
            ).fetchall()
        return {row["stream_id"]: self.load_stream(row["stream_id"]) for row in rows}

    def shutdown(self) -> None:
        """等待写入线程完成并关闭 SQLite 连接。"""
        with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
        self._write_queue.join()
        self._write_queue.put(None)
        self._writer_thread.join(timeout=5)
        with self._conn_lock:
            self._conn.close()
