#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：连续短对话压力观测（Sprint 5.2；Echo 后端，无 GGUF 依赖）。

用法::

    python scripts/stress_test.py --turns 50
"""

from __future__ import annotations

import argparse
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """摘要：运行 N 轮编排并输出耗时与内存峰值。"""
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
    from offline_companion.core.memory_lifecycle.triggers import load_triggers
    from offline_companion.core.persona_session.persona_loader import load_persona_file
    from offline_companion.core.persona_session.session import PersonaSessionCore
    from offline_companion.runtime.inference_backend.mock import EchoBackend
    from offline_companion.runtime.storage_index.engine import connect, new_session
    from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator

    parser = argparse.ArgumentParser(description="offline-companion stress observer")
    parser.add_argument("--turns", type=int, default=50, help="对话轮数")
    parser.add_argument("--memory-on", action="store_true", help="开启记忆召回")
    args = parser.parse_args()

    db = ROOT / ".stress_companion.db"
    if db.is_file():
        db.unlink()
    conn = connect(db)
    persona = load_persona_file(ROOT / "configs" / "personas" / "default.yaml")
    new_session(conn, "stress", persona.persona_id, title=None)
    orch = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("stress"),
        conn=conn,
        session_id="stress",
        triggers=load_triggers(),
    )

    tracemalloc.start()
    times: list[float] = []
    t0 = time.perf_counter()
    for i in range(args.turns):
        user = f"第{i + 1}轮：今天有点累，想聊聊" if i % 5 else f"#remember 偏好条目{i}"
        t1 = time.perf_counter()
        orch.run_turn(user, memory_on=args.memory_on or (i % 3 == 0))
        times.append(time.perf_counter() - t1)
    total = time.perf_counter() - t0
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    mem_n = MemoryLifecycleManager.list_recent_memory(conn, limit=500)
    msg_n = conn.execute("SELECT COUNT(*) FROM messages;").fetchone()[0]
    db_size = db.stat().st_size if db.is_file() else 0

    print("=" * 60)
    print("stress_test 报告")
    print(f"  turns: {args.turns}")
    print(f"  total_wall_s: {total:.2f}")
    print(f"  avg_turn_s: {sum(times) / len(times):.3f}")
    print(f"  max_turn_s: {max(times):.3f}")
    print(f"  tracemalloc_peak_mb: {peak / 1024 / 1024:.2f}")
    print(f"  messages: {msg_n}")
    print(f"  memory_chunks: {len(mem_n)}")
    print(f"  db_bytes: {db_size}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
