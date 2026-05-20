"""audit：知识检索审计日志。"""

from __future__ import annotations

import json
import sqlite3
import time


def log_search(
    conn: sqlite3.Connection,
    *,
    query: str,
    hit_ids: list[int],
    session_id: str | None,
) -> None:
    """摘要：记录一次本地知识检索（可删除、可审计）。"""
    conn.execute(
        "INSERT INTO knowledge_search_log(session_id, query, hit_ids_json, created_at) "
        "VALUES(?,?,?,?);",
        (session_id, query.strip(), json.dumps(hit_ids, ensure_ascii=False), time.time()),
    )
