"""摘要：桌面端扁平设置持久化。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from offline_companion.storage.json_state_store import JsonStateStore

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "light",
    "last_view": "chat",
    "privacy_mode": "local_only",
    "window_bounds": None,
    "shell_custom": {"accent": None, "radius": None, "sidebarWidth": None, "font": None},
    "custom_appearance": {},
    "improve_plan_enabled": False,
    "auto_router_enabled": False,
    "active_model_id": None,
    "active_persona_id": None,
    "close_to_tray": True,
    "memory_enabled": True,
    "idle_think_enabled": True,
    "idle_threshold_seconds": 300,
    "focus_mode_enabled": False,
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
    raw = JsonStateStore(data_root).load(settings_path(data_root), {})
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
    JsonStateStore(data_root).save(settings_path(data_root), payload)
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
