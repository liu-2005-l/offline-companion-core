"""摘要：云端模型配置的本地 JSON 持久化访问层。"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from offline_companion.shared.types import CapabilityProfile
from offline_companion.storage.json_state_store import JsonStateStore


def cloud_models_path(data_root: Path) -> Path:
    """摘要：返回云端模型配置文件路径。

    参数：
        data_root: 应用数据根目录。

    返回值：
        ``cloud_models.json`` 的完整路径。
    """
    return data_root / "cloud_models.json"


def list_cloud_models(data_root: Path) -> list[dict[str, Any]]:
    """摘要：读取全部云端模型配置。

    参数：
        data_root: 应用数据根目录。

    返回值：
        云端模型配置列表；文件缺失或损坏时返回空列表。
    """
    payload = _load(data_root)
    items = payload.get("items", [])
    return [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def list_public_cloud_models(data_root: Path) -> list[dict[str, Any]]:
    """摘要：读取可返回给前端的云端模型配置，API key 只给掩码。

    参数：
        data_root: 应用数据根目录。

    返回值：
        不含明文 API key 的模型列表。
    """
    return [_public_model(item) for item in list_cloud_models(data_root)]


def get_cloud_model(data_root: Path, model_id: str) -> dict[str, Any] | None:
    """摘要：按 ID 读取单个云端模型配置。

    参数：
        data_root: 应用数据根目录。
        model_id: 云端模型 ID。

    返回值：
        匹配的配置；不存在时返回 None。
    """
    for item in list_cloud_models(data_root):
        if str(item.get("id") or "") == model_id:
            return item
    return None


def get_cloud_model_api_key(data_root: Path, model_id: str) -> str | None:
    """摘要：读取本地保存的云模型明文 API key，仅供宿主内部调用。"""
    item = get_cloud_model(data_root, model_id)
    if item is None:
        return None
    key = str(item.get("api_key") or "").strip()
    return key or None


def create_cloud_model(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """摘要：新增云端模型配置并返回安全 payload。

    参数：
        data_root: 应用数据根目录。
        payload: 前端提交的云端模型字段。

    返回值：
        不含明文 API key 的模型 payload。

    Raises:
        ValueError: 必填字段缺失。
    """
    name = _required_text(payload.get("name") or payload.get("model_name"), "name")
    endpoint = _required_text(payload.get("endpoint"), "endpoint")
    model_name = _required_text(payload.get("model_name") or payload.get("name"), "model_name")
    api_key = str(payload.get("api_key") or "").strip()
    capability_profile = _normalize_capability_profile(payload.get("capability_profile"))
    now = time.time()
    item = {
        "id": uuid.uuid4().hex,
        "name": name,
        "endpoint": endpoint,
        "api_key": api_key,
        "model_name": model_name,
        "enabled": bool(payload.get("enabled", True)),
        "source": "local",
        "created_at": now,
        "updated_at": now,
    }
    if capability_profile is not None:
        item["capability_profile"] = capability_profile
    data = _load(data_root)
    items = data.setdefault("items", [])
    if not isinstance(items, list):
        data["items"] = items = []
    items.append(item)
    _save(data_root, data)
    return _public_model(item)


def update_cloud_model(data_root: Path, model_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """摘要：更新云端模型配置并返回安全 payload。

    参数：
        data_root: 应用数据根目录。
        model_id: 云端模型 ID。
        payload: 允许更新的字段。

    返回值：
        更新后的安全 payload；不存在时返回 None。

    Raises:
        ValueError: 字段值不合法。
    """
    data = _load(data_root)
    items = data.get("items", [])
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict) or str(item.get("id") or "") != model_id:
            continue
        if "name" in payload:
            item["name"] = _required_text(payload.get("name"), "name")
        if "endpoint" in payload:
            item["endpoint"] = _required_text(payload.get("endpoint"), "endpoint")
        if "model_name" in payload:
            item["model_name"] = _required_text(payload.get("model_name"), "model_name")
        if "enabled" in payload:
            item["enabled"] = bool(payload.get("enabled"))
        if "api_key" in payload:
            api_key = str(payload.get("api_key") or "").strip()
            if api_key and not api_key.startswith("****"):
                item["api_key"] = api_key
        if "capability_profile" in payload:
            capability_profile = _normalize_capability_profile(payload.get("capability_profile"))
            if capability_profile is None:
                item.pop("capability_profile", None)
            else:
                item["capability_profile"] = capability_profile
        item["updated_at"] = time.time()
        _save(data_root, data)
        return _public_model(item)
    return None


def delete_cloud_model(data_root: Path, model_id: str) -> bool:
    """摘要：删除云端模型配置。

    参数：
        data_root: 应用数据根目录。
        model_id: 云端模型 ID。

    返回值：
        删除成功返回 True；不存在返回 False。
    """
    data = _load(data_root)
    items = data.get("items", [])
    if not isinstance(items, list):
        return False
    remaining = [item for item in items if not isinstance(item, dict) or str(item.get("id") or "") != model_id]
    if len(remaining) == len(items):
        return False
    data["items"] = remaining
    _save(data_root, data)
    return True


def mask_api_key(api_key: str) -> str:
    """摘要：生成 API key 的前端显示掩码。

    参数：
        api_key: 明文 API key。

    返回值：
        掩码字符串；空 key 返回空字符串。
    """
    key = str(api_key or "")
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def _public_model(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("model_name") or ""),
        "endpoint": str(item.get("endpoint") or ""),
        "api_key": mask_api_key(str(item.get("api_key") or "")),
        "model_name": str(item.get("model_name") or item.get("name") or ""),
        "enabled": bool(item.get("enabled", True)),
        "source": str(item.get("source") or "local"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "capability_profile": item.get("capability_profile"),
    }


def _normalize_capability_profile(value: object) -> dict[str, float | int] | None:
    """摘要：校验并规范化云端模型能力画像；旧字符串配置降级为默认画像。"""
    if value is None or isinstance(value, str):
        return None
    if not isinstance(value, dict):
        return None
    try:
        profile = CapabilityProfile(
            instruction_following=float(value.get("instruction_following", 0.5)),
            roleplay_quality=float(value.get("roleplay_quality", 0.5)),
            safety_sensitivity=float(value.get("safety_sensitivity", 0.5)),
            reasoning_ability=float(value.get("reasoning_ability", 0.5)),
            max_context=int(value.get("max_context", 4096)),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid capability_profile: {exc}") from exc
    return {
        "instruction_following": profile.instruction_following,
        "roleplay_quality": profile.roleplay_quality,
        "safety_sensitivity": profile.safety_sensitivity,
        "reasoning_ability": profile.reasoning_ability,
        "max_context": profile.max_context,
    }


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field}_required")
    return text


def _load(data_root: Path) -> dict[str, Any]:
    path = cloud_models_path(data_root)
    payload = JsonStateStore(data_root).load(path, {"items": []})
    return payload if isinstance(payload, dict) else {"items": []}


def _save(data_root: Path, data: dict[str, Any]) -> None:
    JsonStateStore(data_root).save(cloud_models_path(data_root), data)
