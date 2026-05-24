#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：Sprint 6.1 PyInstaller Echo PoC 一键构建（Windows 优先）。

用法::

    python scripts/build_portable.py

产出::

    dist/offline_companion/offline_companion.exe
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "offline_companion"
ENTRY = ROOT / "src" / "offline_companion" / "__main__.py"


def _ensure_pyinstaller() -> None:
    """摘要：确保 PyInstaller 可用。"""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def build(*, onefile: bool = False) -> Path:
    """摘要：调用 PyInstaller 构建便携包。

    参数：
        onefile: 为 True 时使用单文件模式（PoC 默认 onedir 便于排障）。

    返回值：
        生成的 ``.exe`` 路径。
    """
    configs = ROOT / "configs"
    if not configs.is_dir():
        raise SystemExit(f"缺少 configs 目录: {configs}")

    _ensure_pyinstaller()
    add_data = f"{configs}{os.pathsep}configs"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        NAME,
        "--clean",
        "--noconfirm",
        "--console",
        "--paths",
        str(ROOT / "src"),
        "--add-data",
        add_data,
        "--hidden-import",
        "offline_companion",
        "--hidden-import",
        "offline_companion.shell.ui_host.cli",
        "--hidden-import",
        "offline_companion.shell.ui_host.portable_runtime",
        "--exclude-module",
        "llama_cpp",
        "--exclude-module",
        "gradio",
        "--exclude-module",
        "pandas",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "torch",
    ]
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")
    cmd.append(str(ENTRY))

    print("$", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))

    if onefile:
        exe = ROOT / "dist" / f"{NAME}.exe"
    else:
        exe = ROOT / "dist" / NAME / f"{NAME}.exe"
    print(f"[OK] 构建完成 → {exe}")
    return exe


def main() -> int:
    """摘要：CLI 入口。"""
    parser = argparse.ArgumentParser(description="offline-companion PyInstaller Echo PoC")
    parser.add_argument("--onefile", action="store_true", help="单文件模式（默认 onedir）")
    args = parser.parse_args()
    build(onefile=args.onefile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
