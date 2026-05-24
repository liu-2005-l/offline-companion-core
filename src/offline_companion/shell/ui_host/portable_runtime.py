"""portable_runtime：便携包（PyInstaller）首次启动与环境初始化（A1）。"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from offline_companion.shared.runtime_paths import bundled_configs_dir, data_root


def is_frozen() -> bool:
    """摘要：是否运行于 PyInstaller 冻结环境。"""
    return bool(getattr(sys, "frozen", False))


def _seed_configs(data: Path) -> None:
    """摘要：首次启动时将内置 configs 复制到数据目录。"""
    dest = data / "configs"
    marker = dest / "personas" / "default.yaml"
    if marker.is_file():
        return
    src = bundled_configs_dir()
    if src is None or not src.is_dir():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    print(f"[首次启动] 已复制配置到 {dest}")


def _append_startup_log(logs_dir: Path) -> None:
    """摘要：PoC 文件日志：记录启动时间戳（控制台输出不变）。"""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "companion.log"
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"--- portable start {stamp} ---\n")
    except OSError:
        pass


def setup_portable_env() -> Path:
    """摘要：按 ``docs/packaging.md`` 初始化便携包数据目录与环境变量。

    返回值：
        解析后的数据根路径。
    """
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "models").mkdir(exist_ok=True)
    _seed_configs(root)
    logs_dir = root / "logs"
    _append_startup_log(logs_dir)

    os.environ["OFFLINE_COMPANION_DATA_DIR"] = str(root)
    configs = root / "configs"
    persona = configs / "personas" / "default.yaml"
    if persona.is_file():
        os.environ.setdefault("OFFLINE_COMPANION_PERSONA_PATH", str(persona))
    safety = configs / "safety_replies" / "zh_v1.yaml"
    if safety.is_file():
        os.environ.setdefault("OFFLINE_COMPANION_SAFETY_REPLIES", str(safety))
    return root


def _configure_stdio_utf8() -> None:
    """摘要：Windows 控制台 UTF-8，避免中文 print 失败。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def bootstrap_if_frozen() -> Path | None:
    """摘要：冻结 exe 启动时执行便携环境引导。

    返回值：
        数据根路径；非冻结运行时返回 ``None``。
    """
    if not is_frozen():
        return None
    _configure_stdio_utf8()
    return setup_portable_env()
