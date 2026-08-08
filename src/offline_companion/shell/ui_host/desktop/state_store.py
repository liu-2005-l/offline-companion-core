"""桌面壳轻量状态持久化。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    """摘要：读取 JSON 状态文件，文件缺失或损坏时返回空字典。

    参数：
        path: 状态文件路径。

    返回值：
        解析后的字典；不可解析或顶层不是字典时返回空字典。
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def save_json(path: Path, data: dict[str, Any]) -> None:
    """摘要：用同目录临时文件加原子替换写入 JSON 状态。

    参数：
        path: 状态文件路径。
        data: 需要写入的 JSON 字典。
    """
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


def load_plan_store(data_root: Path) -> dict[str, dict[str, Any]]:
    """摘要：加载桌面 HTTP 计划状态。"""
    raw = load_json(_plan_store_path(data_root)).get("plans", {})
    if not isinstance(raw, dict):
        return {}
    return {str(plan_id): dict(plan) for plan_id, plan in raw.items() if isinstance(plan, dict)}


def save_plan_store(data_root: Path, plans: dict[str, dict[str, Any]]) -> None:
    """摘要：保存桌面 HTTP 计划状态。"""
    save_json(_plan_store_path(data_root), {"plans": plans})


def load_extension_state(data_root: Path) -> dict[str, bool]:
    """摘要：加载扩展开关状态。"""
    raw = load_json(_extension_state_path(data_root)).get("enabled", {})
    if not isinstance(raw, dict):
        return {}
    return {str(extension_id): bool(enabled) for extension_id, enabled in raw.items()}


def save_extension_state(data_root: Path, state: dict[str, bool]) -> None:
    """摘要：保存扩展开关状态。"""
    save_json(_extension_state_path(data_root), {"enabled": state})


def _plan_store_path(data_root: Path) -> Path:
    return data_root / "desktop_plans.json"


def _extension_state_path(data_root: Path) -> Path:
    return data_root / "extension_state.json"
