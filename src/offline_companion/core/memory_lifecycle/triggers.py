"""triggers：记忆写入触发器注册表（B2；从 YAML 加载）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from offline_companion.shared.errors import B2TriggerConfigError, B2TriggerConfigNotFoundError
from offline_companion.shared.runtime_paths import configs_dir

TRIGGER_ON_EXPLICIT_SAVE = "on_explicit_save"
TRIGGER_ON_SUMMARIZE_REQUEST = "on_summarize_request"
TRIGGER_ON_EMOTION_SHIFT = "on_emotion_shift"
TRIGGER_ON_SEMANTIC_MEMORY = "on_semantic_memory"


@dataclass(frozen=True)
class TriggerRegistry:
    """摘要：已加载的触发器开关集合。"""

    version: int
    path: Path
    enabled: dict[str, bool]


def default_triggers_path() -> Path:
    """摘要：默认 ``configs/triggers.yaml`` 路径。"""
    return configs_dir() / "triggers.yaml"


def load_triggers(path: Path | None = None) -> TriggerRegistry:
    """摘要：从 YAML 加载触发器开关。"""
    resolved = (path or default_triggers_path()).resolve()
    if not resolved.is_file():
        raise B2TriggerConfigNotFoundError(f"触发器配置不存在: {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise B2TriggerConfigError(f"触发器配置格式错误: {resolved}")
    triggers = raw.get("triggers")
    if not isinstance(triggers, dict):
        raise B2TriggerConfigError(f"触发器配置缺少 triggers: {resolved}")
    enabled: dict[str, bool] = {}
    for name, block in triggers.items():
        if isinstance(block, dict):
            enabled[str(name)] = bool(block.get("enabled", False))
        else:
            enabled[str(name)] = bool(block)
    return TriggerRegistry(version=int(raw.get("version") or 1), path=resolved, enabled=enabled)


def is_enabled(registry: TriggerRegistry | None, name: str) -> bool:
    """摘要：检查触发器是否启用；registry 为 None 时视为未启用。"""
    if registry is None:
        return False
    return bool(registry.enabled.get(name, False))


def _looks_like_memory(user_text: str) -> bool:
    text = user_text.strip()
    keywords = ["记住", "别忘了", "以后叫我", "我的名字是", "我叫", "偏好", "生日", "地址", "电话", "一直记得"]
    return any(k in text for k in keywords)


def maybe_summarize_to_memory(user_text: str, registry: TriggerRegistry) -> list[str] | None:
    if not is_enabled(registry, TRIGGER_ON_SEMANTIC_MEMORY):
        return None
    return [user_text.strip()] if _looks_like_memory(user_text) else None
