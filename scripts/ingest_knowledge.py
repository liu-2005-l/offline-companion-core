#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：将 JSONL 语料导入独立 knowledge.db（运维脚本；语料不进 git 大文件）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """摘要：导入命令入口。"""
    parser = argparse.ArgumentParser(description="Import knowledge JSONL into knowledge.db")
    parser.add_argument("jsonl", type=str, help="Path to .jsonl file")
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="knowledge.db path (default: data root/knowledge.db)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Override app data root (same as companion --data-dir)",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from offline_companion.core.knowledge_rag.ingest import ingest_jsonl_file
    from offline_companion.runtime.storage_index.knowledge_store import (
        connect_knowledge,
        default_knowledge_db_path,
    )
    from offline_companion.shell.policy_engine.rules import default_app_paths

    if args.data_dir:
        root = Path(args.data_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        db_path = Path(args.db).expanduser() if args.db else default_knowledge_db_path(root)
    else:
        paths = default_app_paths()
        db_path = Path(args.db).expanduser() if args.db else default_knowledge_db_path(paths.root)

    conn = connect_knowledge(db_path)
    try:
        n = ingest_jsonl_file(conn, Path(args.jsonl).expanduser())
    finally:
        conn.close()
    print(f"Imported {n} chunks into {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
