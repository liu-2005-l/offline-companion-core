"""packaged_smoke_lib：便携包冒烟逻辑（供 scripts/packaged_smoke.py 与测试复用）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

SMOKE_INPUT = "/memory on\n#remember 便携冒烟偏好\n你好\n/quit\n"


def _decode_stream(data: bytes | None) -> str:
    """摘要：宽容解码便携包输出，避免 Windows 控制台编码差异。"""
    if not data:
        return ""
    for encoding in ("utf-8", "gbk", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def validate_smoke_stdout(text: str) -> list[str]:
    """摘要：校验便携包 REPL 冒烟输出是否满足最小闭环。

    参数：
        text: 子进程合并后的 stdout+stderr。

    返回值：
        未满足条件时的错误说明列表；空列表表示通过。
    """
    errors: list[str] = []
    if "Session:" not in text:
        errors.append("缺少 Session 行")
    if "Memory" not in text and "memory" not in text.lower():
        errors.append("缺少记忆状态输出")
    if "Bot>" not in text:
        errors.append("缺少 Bot> 回复")
    if "saved memory" not in text and "已保存记忆" not in text:
        errors.append("未观察到 #remember 保存提示")
    return errors


def run_packaged_smoke(
    exe: Path,
    *,
    timeout_sec: int = 90,
    data_parent: Path | None = None,
) -> tuple[int, str]:
    """摘要：对便携 exe 执行管道输入冒烟。

    参数：
        exe: ``offline_companion.exe`` 路径。
        timeout_sec: 子进程超时秒数。
        data_parent: 用作平台用户数据根父目录（隔离真实用户数据）。

    返回值：
        ``(退出码, 合并输出文本)``。
    """
    if not exe.is_file():
        return 127, ""

    cleanup_parent = data_parent is None
    parent = data_parent or Path(tempfile.mkdtemp(prefix="offline_packaged_smoke_"))
    parent.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    if os.name == "nt":
        env["LOCALAPPDATA"] = str(parent)
    else:
        env["XDG_DATA_HOME"] = str(parent)

    try:
        proc = subprocess.run(
            [str(exe)],
            input=SMOKE_INPUT.encode("utf-8"),
            capture_output=True,
            env=env,
            timeout=timeout_sec,
            cwd=str(exe.parent),
        )
        combined = _decode_stream(proc.stdout) + _decode_stream(proc.stderr)
        errors = validate_smoke_stdout(combined)
        if errors:
            return 1, combined + "\n[smoke] " + "; ".join(errors)
        if proc.returncode != 0:
            return proc.returncode, combined
        return 0, combined
    finally:
        if cleanup_parent:
            shutil.rmtree(parent, ignore_errors=True)
