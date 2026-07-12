#!/usr/bin/env python3
"""摘要：评测入口（nightly / 手动）；PR 上仅跑快速单测，全量评测在此扩展。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """摘要：运行 pytest 全量或 fixture 回归子集。

    参数：
        命令行 ``--fixtures``：仅 ``tests/test_regression_fixtures.py``。

    返回值：
        子进程退出码。
    """
    parser = argparse.ArgumentParser(description="offline-companion eval runner")
    parser.add_argument(
        "--fixtures",
        action="store_true",
        help="仅运行 fixtures/regression_dialogues.yaml 驱动测试",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="仅运行 test_knowledge_search 等（knowledge|regression）",
    )
    parser.add_argument(
        "--fixture-stats",
        action="store_true",
        help="打印 regression_dialogues.yaml executable/note 统计",
    )
    parser.add_argument(
        "--min-executable",
        type=int,
        default=0,
        help="与 --fixture-stats 联用：executable 数量下限",
    )
    args = parser.parse_args()
    if args.fixture_stats:
        stats = ROOT / "scripts" / "ci" / "fixture_stats.py"
        cmd = [sys.executable, str(stats)]
        if args.min_executable:
            cmd.extend(["--min-executable", str(args.min_executable)])
        return subprocess.call(cmd, cwd=str(ROOT))
    if args.category == "knowledge":
        targets = [str(ROOT / "tests" / "test_knowledge_search.py")]
    elif args.fixtures:
        targets = [
            str(ROOT / "tests" / "test_regression_fixtures.py"),
            str(ROOT / "tests" / "test_fixture_inventory.py"),
        ]
    else:
        targets = [str(ROOT / "tests")]
    cmd = [sys.executable, "-m", "pytest", "-q", *targets]
    code = subprocess.call(cmd, cwd=str(ROOT))
    if code != 0:
        return code
    security_targets = [
        str(ROOT / "tests" / "test_skill_invoker.py"),
        str(ROOT / "tests" / "test_runtime_sandbox.py"),
        str(ROOT / "tests" / "test_ci_checks.py"),
    ]
    sec_cmd = [sys.executable, "-m", "pytest", "-q", *security_targets]
    return subprocess.call(sec_cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
