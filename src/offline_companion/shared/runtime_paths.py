"""runtime_paths：跨层路径解析（数据根、configs 根；无业务逻辑）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def dev_repo_root() -> Path:
    """摘要：开发模式下仓库根目录（``shared`` → ``offline_companion`` → ``src`` → 根）。"""
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    """摘要：用户数据根目录（``OfflineCompanion``）。

    优先级：
        ``OFFLINE_COMPANION_DATA_DIR`` → 系统默认（Windows ``LOCALAPPDATA`` 等）。
    """
    env = os.environ.get("OFFLINE_COMPANION_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA")
        if la:
            return Path(la) / "OfflineCompanion"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "OfflineCompanion"
    return Path.home() / ".local" / "share" / "OfflineCompanion"


def bundled_configs_dir() -> Path | None:
    """摘要：PyInstaller 内置 ``configs/`` 目录（冻结运行时）。"""
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    path = Path(meipass) / "configs"
    return path if path.is_dir() else None


def configs_dir() -> Path:
    """摘要：运行时 configs 根目录。

    优先级：
        数据目录下 ``configs/``（便携模式）→ ``OFFLINE_COMPANION_CONFIGS_DIR`` →
        冻结内置 → 仓库 ``configs/``。
    """
    seeded = data_root() / "configs"
    if (seeded / "personas" / "default.yaml").is_file():
        return seeded
    override = os.environ.get("OFFLINE_COMPANION_CONFIGS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    bundled = bundled_configs_dir()
    if bundled is not None:
        return bundled
    return dev_repo_root() / "configs"
