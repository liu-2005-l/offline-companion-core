"""摘要：扩展启用状态的 SQLite 持久化访问层。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from offline_companion.runtime.storage_index.engine import connect


def init_extension_status(data_root: Path, db_path: Path) -> dict[str, bool]:
    """摘要：初始化扩展状态表，并兼容迁移旧 JSON 状态文件。

    参数：
        data_root: 应用数据根目录，用于查找旧 extension_state.json。
        db_path: companion SQLite 数据库路径。
    返回值：
        当前扩展启用状态映射；未出现的扩展调用方应默认启用。
    """
    _migrate_legacy_json(data_root, db_path)
    return load_extension_status(db_path)


def load_extension_status(db_path: Path) -> dict[str, bool]:
    """摘要：读取已持久化的扩展开关状态。

    参数：
        db_path: companion SQLite 数据库路径。
    返回值：
        extension_id 到 enabled 的映射；空表返回空字典。
    """
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT extension_id, enabled FROM extension_status;").fetchall()
        return {str(row["extension_id"]): bool(row["enabled"]) for row in rows}
    finally:
        conn.close()


def save_extension_status(db_path: Path, extension_id: str, enabled: bool) -> None:
    """摘要：保存单个扩展的启用状态。

    参数：
        db_path: companion SQLite 数据库路径。
        extension_id: 扩展 ID。
        enabled: 是否启用。
    """
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO extension_status(extension_id, enabled, updated_at) VALUES(?,?,strftime('%s','now')) "
            "ON CONFLICT(extension_id) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at;",
            (extension_id, 1 if enabled else 0),
        )
    finally:
        conn.close()


def delete_extension_status(db_path: Path, extension_id: str) -> None:
    """摘要：删除单个扩展的持久化启用状态。

    参数：
        db_path: companion SQLite 数据库路径。
        extension_id: 扩展 ID。
    """
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM extension_status WHERE extension_id = ?;", (extension_id,))
    finally:
        conn.close()


def get_extension_status(db_path: Path, extension_id: str) -> bool:
    """摘要：读取单个扩展状态，未持久化时默认启用。

    参数：
        db_path: companion SQLite 数据库路径。
        extension_id: 扩展 ID。
    返回值：
        扩展是否启用；无记录时返回 True。
    """
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT enabled FROM extension_status WHERE extension_id = ?;",
            (extension_id,),
        ).fetchone()
        return True if row is None else bool(row["enabled"])
    finally:
        conn.close()


def _migrate_legacy_json(data_root: Path, db_path: Path) -> None:
    legacy_path = data_root / "extension_state.json"
    backup_path = data_root / "extension_state.json.bak"
    if not legacy_path.is_file():
        return
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM extension_status;").fetchone()
        if int(row["count"]) > 0:
            return
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        enabled_map = payload.get("enabled", {}) if isinstance(payload, dict) else {}
        if not isinstance(enabled_map, dict):
            return
        for extension_id, enabled in enabled_map.items():
            conn.execute(
                "INSERT OR REPLACE INTO extension_status(extension_id, enabled, updated_at) "
                "VALUES(?,?,strftime('%s','now'));",
                (str(extension_id), 1 if bool(enabled) else 0),
            )
    finally:
        conn.close()
    if not backup_path.exists():
        os.replace(str(legacy_path), str(backup_path))
