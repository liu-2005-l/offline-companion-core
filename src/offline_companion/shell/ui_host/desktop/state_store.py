"""桌面壳轻量状态持久化。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from offline_companion.storage.json_state_store import JsonStateStore


def load_json(path: Path) -> dict[str, Any]:
    """摘要：读取 JSON 状态文件，文件缺失或损坏时返回空字典。

    参数：
        path: 状态文件路径。

    返回值：
        解析后的字典；不可解析或顶层不是字典时返回空字典。
    """
    payload = JsonStateStore(path.parent).load(path, {})
    if not isinstance(payload, dict):
        return {}
    return payload


def save_json(path: Path, data: dict[str, Any]) -> None:
    """摘要：用同目录临时文件加原子替换写入 JSON 状态。

    参数：
        path: 状态文件路径。
        data: 需要写入的 JSON 字典。
    """
    JsonStateStore(path.parent).save(path, data)


def load_extension_state(data_root: Path) -> dict[str, bool]:
    """摘要：加载扩展开关状态。"""
    raw = load_json(_extension_state_path(data_root)).get("enabled", {})
    if not isinstance(raw, dict):
        return {}
    return {str(extension_id): bool(enabled) for extension_id, enabled in raw.items()}


def save_extension_state(data_root: Path, state: dict[str, bool]) -> None:
    """摘要：保存扩展开关状态。"""
    save_json(_extension_state_path(data_root), {"enabled": state})


def _extension_state_path(data_root: Path) -> Path:
    return data_root / "extension_state.json"
