"""knowledge_store：独立知识库 SQLite 连接（C2；与 companion.db 隔离）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from offline_companion.runtime.storage_index.knowledge_schema import migrate_knowledge_db

KNOWLEDGE_SCHEMA_VERSION = 1


def default_knowledge_db_path(data_root: Path) -> Path:
    """摘要：默认 ``knowledge.db`` 路径（位于应用数据根下）。

    参数：
        data_root: 与 ``AppPaths.root`` 一致的数据根。

    返回值：
        ``{data_root}/knowledge.db``。
    """
    return data_root / "knowledge.db"


def connect_knowledge(db_path: Path) -> sqlite3.Connection:
    """摘要：打开知识库并执行迁移。

    参数：
        db_path: SQLite 文件路径。

    返回值：
        已启用 foreign_keys 的连接。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_knowledge_db(conn)
    return conn
