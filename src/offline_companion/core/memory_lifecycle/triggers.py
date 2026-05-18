"""triggers：记忆写入触发器注册表（B2；从 YAML 加载）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import yaml

TRIGGER_ON_EXPLICIT_SAVE = "on_explicit_save"
TRIGGER_ON_SUMMARIZE_REQUEST = "on_summarize_request"
TRIGGER_ON_EMOTION_SHIFT = "on_emotion_shift"


@dataclass(frozen=True)
class TriggerRegistry:
    """摘要：已加载的触发器开关集合。"""

    version: int
    path: Path
    enabled: dict[str, bool]


def default_triggers_path() -> Path:
    """摘要：默认 ``configs/triggers.yaml`` 路径。

    返回值：
        仓库内 triggers 配置绝对路径。
    """
    root = Path(__file__).resolve().parents[4]
    return root / "configs" / "triggers.yaml"


def load_triggers(path: Path | None = None) -> TriggerRegistry:
    """摘要：从 YAML 加载触发器开关。

    参数：
        path: 配置文件；默认 ``default_triggers_path()``。

    返回值：
        ``TriggerRegistry``。

    异常：
        FileNotFoundError：文件不存在。
        ValueError：结构非法。
    """
    resolved = (path or default_triggers_path()).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"触发器配置不存在: {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"触发器配置格式错误: {resolved}")
    triggers = raw.get("triggers")
    if not isinstance(triggers, dict):
        raise ValueError(f"触发器配置缺少 triggers: {resolved}")
    enabled: dict[str, bool] = {}
    for name, block in triggers.items():
        if isinstance(block, dict):
            enabled[str(name)] = bool(block.get("enabled", False))
        else:
            enabled[str(name)] = bool(block)
    return TriggerRegistry(
        version=int(raw.get("version") or 1),
        path=resolved,
        enabled=enabled,
    )


def is_enabled(registry: TriggerRegistry, name: str) -> bool:
    """摘要：查询某触发器是否开启。

    参数：
        registry: 已加载注册表。
        name: 触发器名，如 ``on_explicit_save``。

    返回值：
        配置中存在且 ``enabled`` 为真时 True；未配置视为 False。
    """
    return bool(registry.enabled.get(name, False))


def maybe_summarize_to_memory(user_text: str, registry: TriggerRegistry) -> list[str] | None:
    """摘要：``on_summarize_request`` 钩子（默认关闭，Phase 2 扩展）。

    参数：
        user_text: 用户输入。
        registry: 触发器注册表。

    返回值：
        待写入记忆的行列表；未启用或暂无逻辑时返回 None。
    """
    if not is_enabled(registry, TRIGGER_ON_SUMMARIZE_REQUEST):
        return None
    _ = user_text
    # Sprint 1：仅注册扩展点，不静默写入
    return None
