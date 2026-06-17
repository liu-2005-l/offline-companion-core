#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：Sprint 6.4 便携包（PyInstaller）零交互冒烟（Echo；Windows 优先）。

用法::

    python scripts/build_portable.py
    python scripts/packaged_smoke.py

未构建 ``dist/`` 时默认打印 ``[WARN]`` 并以退出码 0 跳过（便于 Linux CI）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = ROOT / "dist" / "offline_companion" / "offline_companion.exe"

# 脚本入口需能 import 包
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from offline_companion.shell.ui_host.packaged_smoke_lib import run_packaged_smoke  # noqa: E402


def default_portable_exe() -> Path:
    """摘要：默认 PyInstaller 产出 exe 路径。"""
    return DEFAULT_EXE


def main() -> int:
    """摘要：CLI 入口。"""
    parser = argparse.ArgumentParser(description="offline-companion 便携包冒烟")
    parser.add_argument("--exe", type=str, default=None, help="覆盖 exe 路径")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="未找到 exe 或冒烟失败时返回非零（默认仅 WARN 后跳过）",
    )
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    exe = Path(args.exe).expanduser() if args.exe else default_portable_exe()
    if not exe.is_file():
        print(f"[WARN] 未找到便携包: {exe}（先运行 python scripts/build_portable.py）")
        return 1 if args.strict else 0

    code, out = run_packaged_smoke(exe, timeout_sec=args.timeout)
    if out:
        print(out[-4000:])
    if code == 0:
        print("[OK] 便携包冒烟通过")
        return 0
    print("[FAIL] 便携包冒烟未通过", file=sys.stderr)
    return code if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
