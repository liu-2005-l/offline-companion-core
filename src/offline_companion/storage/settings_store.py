"""摘要：桌面端扁平设置持久化。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "light",
    "last_view": "chat",
    "privacy_mode": "local_only",
    "window_bounds": None,
    "shell_custom": {"accent": None, "radius": None, "sidebarWidth": None, "font": None},
    "custom_appearance": {},
    "improve_plan_enabled": False,
    "auto_router_enabled": False,
    "active_persona_id": None,
    "close_to_tray": True,
    "memory_enabled": True,
}


def settings_path(data_root: Path) -> Path:
    """摘要：返回 settings.json 的标准路径。

    参数：
        data_root: 应用数据根目录。
    返回值：
        settings.json 文件路径。
    """
    return data_root / "settings.json"


def load_settings(data_root: Path) -> dict[str, Any]:
    """摘要：读取本地设置，缺失或损坏时返回默认值。

    参数：
        data_root: 应用数据根目录。
    返回值：
        合并默认值后的扁平设置字典。
    """
    path = settings_path(data_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update(raw)
    return settings


def save_settings(data_root: Path, settings: dict[str, Any]) -> dict[str, Any]:
    """摘要：原子写入完整设置字典。

    参数：
        data_root: 应用数据根目录。
        settings: 要保存的设置。
    返回值：
        合并默认值和更新时间后的设置。
    """
    payload = dict(DEFAULT_SETTINGS)
    payload.update(settings)
    payload["updated_at"] = time.time()
    _save_json(settings_path(data_root), payload)
    return payload


def update_settings(data_root: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """摘要：读取当前设置并应用局部更新。

    参数：
        data_root: 应用数据根目录。
        patch: 需要更新的键值。
    返回值：
        保存后的完整设置。
    """
    current = load_settings(data_root)
    current.update(patch)
    return save_settings(data_root, current)


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(str(tmp_path), str(path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
