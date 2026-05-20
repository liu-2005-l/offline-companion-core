"""ingest：离线语料导入 knowledge.db。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def ingest_jsonl_file(conn: sqlite3.Connection, path: Path) -> int:
    """摘要：从 JSONL 导入文档块（每行一个 JSON 对象）。

    参数：
        conn: 知识库连接。
        path: ``.jsonl`` 文件路径。

    期望值字段：
        ``title``、``body`` 必填；``source_uri``、``license_note`` 可选。

    返回值：
        导入的 chunk 条数。
    """
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj: dict[str, Any] = json.loads(line)
        body = str(obj.get("body") or "").strip()
        if not body:
            continue
        title = str(obj.get("title") or "untitled")
        source_uri = str(obj.get("source_uri") or f"file://{path.name}")
        license_note = str(obj.get("license_note") or "")
        ingest_chunk(conn, title=title, source_uri=source_uri, body=body, license_note=license_note)
        count += 1
    return count


def ingest_chunk(
    conn: sqlite3.Connection,
    *,
    title: str,
    source_uri: str,
    body: str,
    license_note: str = "",
) -> int:
    """摘要：写入单条文档与正文块。

    返回值：
        新建 ``knowledge_chunks.id``。
    """
    now = time.time()
    cur = conn.execute(
        "INSERT INTO knowledge_documents(title, source_uri, license_note, ingested_at) "
        "VALUES(?,?,?,?);",
        (title.strip(), source_uri.strip(), license_note.strip(), now),
    )
    doc_id = int(cur.lastrowid or 0)
    cur2 = conn.execute(
        "INSERT INTO knowledge_chunks(doc_id, body, meta_json) VALUES(?,?,?);",
        (doc_id, body.strip(), "{}"),
    )
    rid = cur2.lastrowid
    assert rid is not None
    return int(rid)
