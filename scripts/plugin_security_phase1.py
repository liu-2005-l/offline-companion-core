#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：Plugin 安全隔离第一阶段验证入口。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _configure_stdio_utf8() -> None:
    """摘要：兼容 Windows 控制台 UTF-8 输出。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _resolve_python(requested: str) -> list[str]:
    """摘要：解析可用 Python 命令。

    参数：
        requested: 用户显式传入的解释器路径。

    返回：
        可直接传给 ``subprocess.run`` 的命令前缀。
    """
    if requested:
        requested_path = Path(requested).resolve()
        if not requested_path.exists():
            raise SystemExit(f"指定的 Python 不存在：{requested_path}")
        return [str(requested_path)]

    current_python = Path(sys.executable).resolve()
    if current_python.exists():
        return [str(current_python)]

    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return [str(venv_python)]

    python_cmd = shutil.which("python")
    if python_cmd and "WindowsApps" not in python_cmd:
        return [python_cmd]

    py_cmd = shutil.which("py")
    if py_cmd:
        return [py_cmd, "-3.11"]

    raise SystemExit("未找到可用 Python。请传入 --python-exe，或先准备 .venv\\Scripts\\python.exe。")


def _build_env() -> dict[str, str]:
    """摘要：构造子进程环境。"""
    env = {**os.environ}
    env["PYTHONPATH"] = str(SRC)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _run(cmd: list[str]) -> int:
    """摘要：执行子命令并透传退出码。"""
    print("RUN", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=ROOT, env=_build_env(), check=False)
    return int(completed.returncode)


def main() -> int:
    """摘要：解析参数并执行对应验证步骤。"""
    _configure_stdio_utf8()

    parser = argparse.ArgumentParser(prog="plugin_security_phase1")
    parser.add_argument("mode", choices=("tests", "desktop"))
    parser.add_argument("--python-exe", default="", help="显式指定 Python 解释器路径")
    parser.add_argument("--force", action="store_true", help="桌面模式下透传 --force")
    args = parser.parse_args()

    python_prefix = _resolve_python(args.python_exe)
    if args.mode == "tests":
        return _run([*python_prefix, "-m", "pytest", "tests/test_plugin_security.py", "-v"])

    cmd = [*python_prefix, "-m", "offline_companion.shell.ui_host.cli", "desktop"]
    if args.force:
        cmd.append("--force")
    return _run(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
