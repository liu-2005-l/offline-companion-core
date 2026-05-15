#!/usr/bin/env python3
"""摘要：评测入口（nightly / 手动）；PR 上仅跑快速单测，全量评测在此扩展。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """摘要：运行当前仓库可用的评测/测试子集。"""
    cmd = [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")]
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
