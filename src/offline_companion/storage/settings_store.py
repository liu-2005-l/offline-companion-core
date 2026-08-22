"""摘要：桌面端扁平设置持久化。"""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any

from offline_companion.storage.json_state_store import JsonStateStore

SETTINGS_MODULES = frozenset({"appearance", "window", "model", "privacy", "behavior", "session", "memory"})

DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": 2,
    "appearance": {"theme": "light", "accent": {"color": "#3b82f6", "hover": "#2563eb", "soft": "#dbeafe", "name": "默认蓝"}, "corner_radius": 12, "sidebar_width": 56},
    "window": {"bounds": {"x": 100, "y": 100, "width": 1080, "height": 720, "maximized": False}},
    "model": {"active_persona_id": None, "auto_router_enabled": False, "local_model_id": None, "cloud_model_id": None},
    "privacy": {"privacy_mode": "LOCAL_ONLY"},
    "behavior": {
        "improve_plan_enabled": False,
        "decomp_learning_enabled": True,
        "idle_think_enabled": True,
        "desktop_notification_enabled": True,
        "close_to_tray": True,
        "memory_enabled": True,
        "idle_threshold_seconds": 300,
        "focus_mode_enabled": False,
    },
    "session": {"active_session_id": None, "last_view": "chat"},
    "memory": {"extraction_interval": 10, "recall_top_k": 5, "decay_half_life_days": 30},
    "onboarding": {"completed": False, "step": 0, "skipped_model": False},
}

LEGACY_DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "light",
    "last_view": "chat",
    "privacy_mode": "local_only",
    "window_bounds": None,
    "shell_custom": {"accent": None, "radius": None, "sidebarWidth": None, "font": None},
    "custom_appearance": {},
    "improve_plan_enabled": False,
    "decomp_learning_enabled": True,
    "auto_router_enabled": False,
    "active_model_id": None,
    "active_persona_id": None,
    "close_to_tray": True,
    "memory_enabled": True,
    "idle_think_enabled": True,
    "idle_threshold_seconds": 300,
    "focus_mode_enabled": False,
}

_LEGACY_DISK_KEYS = frozenset(LEGACY_DEFAULT_SETTINGS)
_SETTINGS_LOCK = threading.RLock()


def settings_path(data_root: Path) -> Path:
    """摘要：返回 settings.json 的标准路径。

    参数：
        data_root: 应用数据根目录。
    返回值：
        settings.json 文件路径。
    """
    return data_root / "settings.json"


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _known_patch(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """摘要：过滤设置模块中未声明的字段，递归保留已知嵌套字段。"""
    result: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in current:
            continue
        if isinstance(value, dict) and isinstance(current[key], dict):
            result[key] = _known_patch(current[key], value)
        else:
            expected = current[key]
            if isinstance(expected, bool) and not isinstance(value, bool):
                raise TypeError(f"invalid type for settings field: {key}")
            if isinstance(expected, (int, float)) and not isinstance(value, (int, float)):
                raise TypeError(f"invalid type for settings field: {key}")
            if isinstance(expected, str) and not isinstance(value, str):
                raise TypeError(f"invalid type for settings field: {key}")
            result[key] = copy.deepcopy(value)
    return result


def migrate_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """摘要：将旧扁平设置映射到 v2 功能模块。"""
    custom = raw.get("shell_custom") if isinstance(raw.get("shell_custom"), dict) else {}
    bounds = raw.get("window_bounds") if isinstance(raw.get("window_bounds"), dict) else DEFAULT_SETTINGS["window"]["bounds"]
    return _deep_merge(DEFAULT_SETTINGS, {
        "appearance": {"theme": raw.get("theme", "light"), "accent": custom.get("accent") or DEFAULT_SETTINGS["appearance"]["accent"], "corner_radius": custom.get("radius") or 12, "sidebar_width": custom.get("sidebar_width", custom.get("sidebarWidth", 56))},
        "window": {"bounds": bounds},
        "model": {"active_persona_id": raw.get("active_persona_id"), "auto_router_enabled": raw.get("auto_router_enabled", False), "local_model_id": raw.get("active_model_id")},
        "privacy": {"privacy_mode": str(raw.get("privacy_mode", "LOCAL_ONLY")).upper()},
        "behavior": {
            "improve_plan_enabled": raw.get("improve_plan_enabled", False),
            "decomp_learning_enabled": raw.get("decomp_learning_enabled", True),
            "idle_think_enabled": raw.get("idle_think_enabled", True),
            "desktop_notification_enabled": raw.get("desktop_notification_enabled", True),
            "close_to_tray": raw.get("close_to_tray", True),
            "memory_enabled": raw.get("memory_enabled", True),
            "idle_threshold_seconds": raw.get("idle_threshold_seconds", 300),
            "focus_mode_enabled": raw.get("focus_mode_enabled", False),
        },
        "session": {"active_session_id": raw.get("active_session_id"), "last_view": raw.get("last_view", "chat")},
        "onboarding": raw.get("onboarding", DEFAULT_SETTINGS["onboarding"]),
        "memory": raw.get("memory", {}),
    })


def _canonical_settings(data_root: Path, *, persist_missing: bool = True) -> dict[str, Any]:
    with _SETTINGS_LOCK:
        raw = JsonStateStore(data_root).load(settings_path(data_root), {})
        if not isinstance(raw, dict):
            raw = {}
        if raw.get("schema_version") != 2:
            if not raw and not settings_path(data_root).exists() and not persist_missing:
                return copy.deepcopy(DEFAULT_SETTINGS)
            if raw:
                backup = data_root / "settings.v1.bak.json"
                if not backup.exists():
                    JsonStateStore(data_root).save(backup, raw)
            migrated = migrate_v1_to_v2(raw)
            JsonStateStore(data_root).save(settings_path(data_root), _disk_payload(migrated))
            return migrated
        canonical = _deep_merge(DEFAULT_SETTINGS, raw)
        for key in _LEGACY_DISK_KEYS:
            canonical.pop(key, None)
        return canonical


def _legacy_aliases(settings: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(settings)
    result.update({
        "theme": settings["appearance"]["theme"],
        "last_view": settings["session"]["last_view"],
        "privacy_mode": str(settings["privacy"]["privacy_mode"]).lower(),
        "improve_plan_enabled": settings["behavior"]["improve_plan_enabled"],
        "decomp_learning_enabled": settings["behavior"]["decomp_learning_enabled"],
        "auto_router_enabled": settings["model"]["auto_router_enabled"],
        "active_persona_id": settings["model"]["active_persona_id"],
        "active_model_id": settings["model"].get("local_model_id"),
        "active_session_id": settings["session"]["active_session_id"],
        "window_bounds": None if settings["window"]["bounds"] == DEFAULT_SETTINGS["window"]["bounds"] else settings["window"]["bounds"],
        "shell_custom": {"accent": None, "radius": None, "sidebarWidth": None, "font": None},
        "custom_appearance": {},
        "close_to_tray": settings["behavior"]["close_to_tray"],
        "memory_enabled": settings["behavior"]["memory_enabled"],
        "idle_think_enabled": settings["behavior"]["idle_think_enabled"],
        "idle_threshold_seconds": settings["behavior"]["idle_threshold_seconds"],
        "focus_mode_enabled": settings["behavior"]["focus_mode_enabled"],
    })
    return result


def _disk_payload(settings: dict[str, Any]) -> dict[str, Any]:
    """摘要：构造 v2 设置文件并保留旧版本读取所需的兼容字段。"""
    return _legacy_aliases(settings)


def get_all(data_root: Path) -> dict[str, Any]:
    """摘要：读取完整 v2 设置。"""
    return _canonical_settings(data_root)


def get_module(data_root: Path, module: str) -> dict[str, Any] | None:
    """摘要：读取指定设置模块。"""
    value = _canonical_settings(data_root).get(module)
    return copy.deepcopy(value) if isinstance(value, dict) else None


def patch_module(data_root: Path, module: str, patch: dict[str, Any]) -> dict[str, Any]:
    """摘要：对指定模块执行 deep merge 并持久化。"""
    if module not in SETTINGS_MODULES:
        raise KeyError(module)
    if not isinstance(patch, dict):
        raise TypeError("settings patch must be an object")
    with _SETTINGS_LOCK:
        settings = _canonical_settings(data_root)
        known_patch = _known_patch(settings[module], patch)
        settings[module] = _deep_merge(settings[module], known_patch)
        settings["updated_at"] = time.time()
        JsonStateStore(data_root).save(settings_path(data_root), _disk_payload(settings))
        return copy.deepcopy(settings[module])


def load_settings(data_root: Path) -> dict[str, Any]:
    """摘要：读取本地设置，缺失或损坏时返回默认值。

    参数：
        data_root: 应用数据根目录。
    返回值：
        合并默认值后的扁平设置字典。
    """
    return _legacy_aliases(_canonical_settings(data_root, persist_missing=False))


def save_settings(data_root: Path, settings: dict[str, Any]) -> dict[str, Any]:
    """摘要：原子写入完整设置字典。

    参数：
        data_root: 应用数据根目录。
        settings: 要保存的设置。
    返回值：
        合并默认值和更新时间后的设置。
    """
    payload = settings if settings.get("schema_version") == 2 else migrate_v1_to_v2(settings)
    payload = _deep_merge(DEFAULT_SETTINGS, payload)
    payload["updated_at"] = time.time()
    JsonStateStore(data_root).save(settings_path(data_root), _disk_payload(payload))
    return _legacy_aliases(payload)


def update_settings(data_root: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """摘要：读取当前设置并应用局部更新。

    参数：
        data_root: 应用数据根目录。
        patch: 需要更新的键值。
    返回值：
        保存后的完整设置。
    """
    if any(key in SETTINGS_MODULES for key in patch):
        current = _canonical_settings(data_root)
        current = _deep_merge(current, patch)
        return save_settings(data_root, current)
    current = _legacy_aliases(_canonical_settings(data_root))
    current.update(patch)
    return save_settings(data_root, migrate_v1_to_v2(current))
