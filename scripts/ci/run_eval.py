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
    args = parser.parse_args()
    if args.fixtures:
        targets = [str(ROOT / "tests" / "test_regression_fixtures.py")]
    else:
        targets = [str(ROOT / "tests")]
    cmd = [sys.executable, "-m", "pytest", "-q", *targets]
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
