"""manager：B2 记忆生命周期编排（含导出载荷组装与导入应用）。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from offline_companion.shared.errors import BundleFormatError
from offline_companion.shared.types import BUNDLE_FORMAT, BUNDLE_VERSION, ExportBundlePayload

from . import fts_ops


def _table_jsonl(conn: sqlite3.Connection, table: str) -> str:
    rows = conn.execute(f"SELECT * FROM {table};").fetchall()
    lines: list[str] = []
    for r in rows:
        lines.append(json.dumps({k: r[k] for k in r.keys()}, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def _read_jsonl(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


class MemoryLifecycleManager:
    """摘要：对外暴露记忆 CRUD、导出载荷组装与导入应用。"""

    add_memory_chunk = staticmethod(fts_ops.add_memory_chunk)
    search_memory = staticmethod(fts_ops.search_memory)
    list_recent_memory = staticmethod(fts_ops.list_recent_memory)
    delete_memory_chunk = staticmethod(fts_ops.delete_memory_chunk)
    update_memory_chunk = staticmethod(fts_ops.update_memory_chunk)
    maybe_extract_memory_commands = staticmethod(fts_ops.maybe_extract_memory_commands)
    format_memory_block = staticmethod(fts_ops.format_memory_block)


def prepare_export_bundle(
    conn: sqlite3.Connection,
    *,
    persona_snapshot: dict[str, Any],
) -> ExportBundlePayload:
    """摘要：从权威库组装导出载荷（业务取舍在此完成）。

    参数：
        conn: SQLite 连接。
        persona_snapshot: 人设快照字典。

    返回值：
        供 C2 `write_bundle_archive` 使用的载荷。
    """
    persona_json = json.dumps(persona_snapshot, ensure_ascii=False, indent=2)
    sessions_jsonl = _table_jsonl(conn, "sessions")
    messages_jsonl = _table_jsonl(conn, "messages")
    memory_chunks_jsonl = _table_jsonl(conn, "memory_chunks")
    digest_src = persona_json + sessions_jsonl + messages_jsonl + memory_chunks_jsonl
    payload_digest = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()
    manifest: dict[str, Any] = {
        "format": BUNDLE_FORMAT,
        "bundle_version": BUNDLE_VERSION,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "db_schema_version": 1,
        "privacy_note": (
            "This archive may contain private conversation text and memory snippets. "
            "Treat it as sensitive; encryption at rest is not applied by this exporter."
        ),
        "sha256_persona_json": hashlib.sha256(persona_json.encode("utf-8")).hexdigest(),
        "integrity": {"algorithm": "sha256", "signature": None, "payload_digest": payload_digest},
    }
    return ExportBundlePayload(
        manifest=manifest,
        persona_json=persona_json,
        sessions_jsonl=sessions_jsonl,
        messages_jsonl=messages_jsonl,
        memory_chunks_jsonl=memory_chunks_jsonl,
    )


def apply_bundle_import(
    conn: sqlite3.Connection,
    payload: ExportBundlePayload,
    *,
    prefix_session: str = "imp",
) -> dict[str, Any]:
    """摘要：将载荷导入当前连接的数据库（生成新 session id）。"""
    if payload.manifest.get("format") != BUNDLE_FORMAT:
        raise BundleFormatError("unknown bundle format")
    sessions = _read_jsonl(payload.sessions_jsonl)
    messages = _read_jsonl(payload.messages_jsonl)
    memory = _read_jsonl(payload.memory_chunks_jsonl)

    id_map: dict[str, str] = {}
    for s in sessions:
        old = str(s["id"])
        id_map[old] = f"{prefix_session}-{old}"

    now = time.time()
    for s in sessions:
        old_id = str(s["id"])
        conn.execute(
            "INSERT INTO sessions(id, title, persona_id, created_at, updated_at) "
            "VALUES(?,?,?,?,?);",
            (
                id_map[old_id],
                s.get("title"),
                str(s["persona_id"]),
                float(s["created_at"]),
                now,
            ),
        )

    for m in messages:
        sid = id_map.get(str(m["session_id"]))
        if not sid:
            continue
        conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at, meta_json) "
            "VALUES(?,?,?,?,?);",
            (
                sid,
                str(m["role"]),
                str(m["content"]),
                float(m["created_at"]),
                str(m.get("meta_json") or "{}"),
            ),
        )

    for mem in memory:
        old_sid = mem.get("session_id")
        new_sid = id_map.get(str(old_sid)) if old_sid else None
        conn.execute(
            "INSERT INTO memory_chunks(session_id, source, body, created_at, updated_at, meta_json) "
            "VALUES(?,?,?,?,?,?);",
            (
                new_sid,
                str(mem["source"]),
                str(mem["body"]),
                float(mem["created_at"]),
                float(mem["updated_at"]),
                str(mem.get("meta_json") or "{}"),
            ),
        )

    return {"imported_sessions": len(sessions), "id_map": id_map}
