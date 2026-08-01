"""runtime_paths：跨层路径解析（数据根、configs 根；无业务逻辑）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    """摘要：动态检测是否运行于 PyInstaller 冻结环境。"""
    return bool(getattr(sys, "frozen", False))


def _get_meipass() -> str | None:
    """摘要：动态获取 PyInstaller bundle 根目录。"""
    if not _is_frozen():
        return None
    return getattr(sys, "_MEIPASS", None)


def dev_repo_root() -> Path:
    """摘要：仓库根目录。

    开发模式：``shared`` → ``offline_companion`` → ``src`` → 根。
    冻结模式：退化为 PyInstaller bundle 根（_MEIPASS，只读）。
    """
    meipass = _get_meipass()
    if meipass:
        return Path(meipass)
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
    meipass = _get_meipass()
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


def models_dir(*, data_root_override: Path | None = None) -> Path:
    """摘要：本地 GGUF 模型目录。

    优先级：
        ``OFFLINE_COMPANION_MODELS_DIR`` →
        仓库 ``models/``（仅开发模式，存在 ``registry.yaml`` 时）→
        ``{data_root}/models/``（冻结模式和用户数据目录）。
    """
    env = os.environ.get("OFFLINE_COMPANION_MODELS_DIR")
    if env:
        path = Path(env).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    if _is_frozen() and data_root_override is None:
        installed_models = Path(sys.executable).resolve().parent / "models"
        if installed_models.is_dir() and any(installed_models.glob("*.gguf")):
            return installed_models

    if not _is_frozen():
        repo_models = dev_repo_root() / "models"
        if (repo_models / "registry.yaml").is_file():
            return repo_models

    root = data_root_override if data_root_override is not None else data_root()
    path = root / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path
