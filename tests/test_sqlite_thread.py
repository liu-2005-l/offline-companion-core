"""SQLite 连接跨线程（桌面壳 / Flask threaded 回归）。"""

from __future__ import annotations

import threading

from offline_companion.runtime.storage_index.engine import connect, new_session


def test_connect_allows_other_thread_read(tmp_path) -> None:
    conn = connect(tmp_path / "t.db")
    new_session(conn, "s1", "default", title=None)
    err: list[BaseException] = []

    def worker() -> None:
        try:
            row = conn.execute("SELECT id FROM sessions WHERE id = ?;", ("s1",)).fetchone()
            assert row is not None
        except (AssertionError, RuntimeError, TypeError, ValueError) as e:
            err.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert not err


def test_connect_enables_wal_and_normal_sync(tmp_path) -> None:
    """连接初始化应启用 WAL 与 NORMAL 同步策略。"""
    conn = connect(tmp_path / "wal.db")
    busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
    assert int(busy_timeout) == 5000
    assert str(journal_mode).lower() == "wal"
    assert int(synchronous) == 1
