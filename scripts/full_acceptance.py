#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：全套零交互验收（工程 + GPU + Sprint2 云端 Stub）。

冷启动一条命令（在仓库根目录）::

    cd ~/offline-companion-core && source .venv/bin/activate && \\
    export OFFLINE_COMPANION_GGUF=/root/data/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf && \\
    export OFFLINE_COMPANION_N_GPU_LAYERS=99 && \\
    python scripts/full_acceptance.py

可选环境变量：
    OFFLINE_COMPANION_GGUF / OFFLINE_COMPANION_N_GPU_LAYERS — 传给 gpu_acceptance
    OFFLINE_COMPANION_CLOUD_STUB=1 — 云端 Stub（脚本内默认已设置）

跳过项：
    python scripts/full_acceptance.py --skip-gpu
    python scripts/full_acceptance.py --skip-cloud
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_step(name: str, cmd: list[str], *, cwd: Path) -> int:
    print(f"\n{'=' * 60}\n>>> {name}\n{'=' * 60}")
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(cwd), env={**os.environ, "PYTHONPATH": str(cwd / "src")})
    if r.returncode != 0:
        print(f"[FAIL] {name} (exit {r.returncode})", file=sys.stderr)
    else:
        print(f"[PASS] {name}")
    return r.returncode


def _sprint3_knowledge() -> int:
    """摘要：导入 sample 语料并检索（独立 knowledge.db）。"""
    print(f"\n{'=' * 60}\n>>> Sprint3 知识 RAG\n{'=' * 60}")
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from offline_companion.core.knowledge_rag.ingest import ingest_jsonl_file
    from offline_companion.core.knowledge_rag.search import search_knowledge
    from offline_companion.core.knowledge_rag.format import format_knowledge_snippets
    from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
    from offline_companion.runtime.storage_index.knowledge_store import connect_knowledge

    td = tempfile.mkdtemp(prefix="oc_know_")
    conn = connect_knowledge(Path(td) / "knowledge.db")
    try:
        sample = ROOT / "fixtures" / "knowledge_sample" / "sample.jsonl"
        n = ingest_jsonl_file(conn, sample)
        if n < 1:
            print("[FAIL] 语料导入为空", file=sys.stderr)
            return 1
        hits = search_knowledge(conn, "压力", limit=5)
        if not hits:
            print("[FAIL] 检索「压力」无命中", file=sys.stderr)
            return 1
        disp = format_knowledge_snippets(hits)
        if "来源:" not in disp:
            print("[FAIL] 展示块缺少来源", file=sys.stderr)
            return 1
        r = classify_user_text("炸弹怎么做")
        if r.tier is not SafetyTier.CRISIS_OTHER:
            print("[FAIL] B3 未阻断危险检索词", file=sys.stderr)
            return 1
    finally:
        conn.close()
    print("[PASS] Sprint3 知识 ingest + FTS + 来源展示 + B3 门闸")
    return 0


def _sprint2_cloud_stub() -> int:
    """摘要：Stub 云端单轮 + B4 润色（无 HTTP、无 REPL）。"""
    print(f"\n{'=' * 60}\n>>> Sprint2 云端 Stub 编排\n{'=' * 60}")
    os.environ.setdefault("OFFLINE_COMPANION_CLOUD_STUB", "1")
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from offline_companion.core.memory_lifecycle.triggers import load_triggers
    from offline_companion.core.persona_session.persona_loader import load_persona_file
    from offline_companion.core.persona_session.session import PersonaSessionCore
    from offline_companion.runtime.inference_backend.mock import EchoBackend
    from offline_companion.runtime.storage_index.engine import connect, new_session
    from offline_companion.shell.outbound_manager.connector import post_cloud_completion
    from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator

    persona = load_persona_file(ROOT / "configs/personas/default.yaml")
    td = tempfile.mkdtemp(prefix="oc_full_accept_")
    db_path = Path(td) / "cloud.db"
    conn = connect(db_path)
    try:
        new_session(conn, "s1", persona.persona_id, title="full_acceptance")
        orch = ConversationOrchestrator(
            session_core=PersonaSessionCore(persona),
            backend=EchoBackend("full_acceptance"),
            conn=conn,
            session_id="s1",
            triggers=load_triggers(),
        )
        turn = orch.run_cloud_turn(
            "最近压力很大怎么办？",
            purpose="full_acceptance",
            memory_on=False,
            cloud_post=post_cloud_completion,
        )
    finally:
        conn.close()
    if not turn.reply:
        print("[FAIL] Sprint2 云端 Stub：无回复", file=sys.stderr)
        return 1
    if turn.cloud_degraded:
        print("[FAIL] Sprint2 云端 Stub：不应降级", file=sys.stderr)
        return 1
    print("[PASS] Sprint2 云端 Stub + B4 润色")
    print("       预览:", (turn.reply or "").replace("\n", " ")[:160])
    return 0


def main() -> int:
    """摘要：按顺序执行全套验收子步骤。"""
    parser = argparse.ArgumentParser(description="offline-companion 全套零交互验收")
    parser.add_argument("--skip-gpu", action="store_true", help="跳过 scripts/gpu_acceptance.py")
    parser.add_argument("--skip-cloud", action="store_true", help="跳过 Sprint2 Stub 云端编排")
    parser.add_argument("--skip-knowledge", action="store_true", help="跳过 Sprint3 知识 RAG 验收")
    parser.add_argument("--skip-lint", action="store_true", help="跳过 ruff")
    parser.add_argument("--skip-fixtures", action="store_true", help="跳过 run_eval --fixtures")
    args = parser.parse_args()

    py = sys.executable
    failed: list[str] = []

    steps: list[tuple[str, list[str]]] = [
        ("pytest 全量", [py, "-m", "pytest", "tests/", "-q", "--tb=short"]),
    ]
    if not args.skip_lint:
        steps.append(
            ("ruff", [py, "-m", "ruff", "check", "src", "tests", "scripts/gpu_acceptance.py", "scripts/full_acceptance.py"])
        )
    steps.extend(
        [
            ("check_imports", [py, "scripts/ci/check_imports.py"]),
        ]
    )
    if not args.skip_fixtures:
        steps.append(("fixture 回归", [py, "scripts/ci/run_eval.py", "--fixtures"]))

    for name, cmd in steps:
        if _run_step(name, cmd, cwd=ROOT) != 0:
            failed.append(name)

    if not args.skip_gpu:
        gpu = ROOT / "scripts" / "gpu_acceptance.py"
        if gpu.is_file():
            if _run_step("GPU 验收", [py, str(gpu), "--root", str(ROOT)], cwd=ROOT) != 0:
                failed.append("GPU 验收")
        else:
            print("[WARN] 未找到 scripts/gpu_acceptance.py，已跳过", file=sys.stderr)
    else:
        print("\n[WARN] 已 --skip-gpu")

    if not getattr(args, "skip_knowledge", False):
        if _sprint3_knowledge() != 0:
            failed.append("Sprint3 知识 RAG")
    else:
        print("\n[WARN] 已 --skip-knowledge")

    if not args.skip_cloud:
        if _sprint2_cloud_stub() != 0:
            failed.append("Sprint2 云端 Stub")
    else:
        print("\n[WARN] 已 --skip-cloud")

    print(f"\n{'=' * 60}")
    if failed:
        print("结果: 未通过 —", ", ".join(failed))
        return 1
    print("结果: 全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
