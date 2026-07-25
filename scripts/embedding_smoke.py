#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：记忆向量功能域冒烟入口。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _configure_stdio_utf8() -> None:
    """摘要：Windows 控制台输出编码兜底。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    """摘要：验证 embedding 默认关闭与存储 schema。"""
    _configure_stdio_utf8()
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    from offline_companion.core.memory_lifecycle.embedding_config import load_embedding_config
    from offline_companion.runtime.storage_index.engine import connect

    cfg = load_embedding_config()
    if cfg.enabled:
        print("[FAIL] embedding.yaml 默认应为 enabled: false", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="oc_emb_") as td:
        conn = connect(Path(td) / "c.db")
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_chunks);").fetchall()}
            required = {"embedding_blob", "embedding_model", "embedding_dim"}
            missing = required - cols
            if missing:
                print(f"[FAIL] memory_chunks 缺少向量字段：{sorted(missing)}", file=sys.stderr)
                return 1
        finally:
            conn.close()

    print("[PASS] 记忆向量：默认关闭 + schema 字段完整")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
