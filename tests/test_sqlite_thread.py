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
        except BaseException as e:
            err.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert not err
