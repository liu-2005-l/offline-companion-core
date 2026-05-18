"""persona_loader：人设 YAML 加载与基础校验（B1）。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from offline_companion.shared.types import Persona

_DEFAULT_COMPANION_DISPLAY_NAME = "助手一号"


def load_persona_file(path: Path) -> Persona:
    """摘要：从 YAML 文件加载人设。

    参数：
        path: YAML 路径。

    返回值：
        ``Persona`` 实例。

    异常：
        ValueError：缺少必需字段。
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pid = str(data.get("id") or path.stem)
    name = str(data.get("name") or pid)
    system_prompt = str(data.get("system_prompt") or "").strip()
    if not system_prompt:
        raise ValueError(f"Persona {path} missing system_prompt")
    role_lock = bool(data.get("role_lock", True))
    memory_default_on = bool(data.get("memory_default_on", True))
    default_display = str(data.get("default_companion_display_name") or _DEFAULT_COMPANION_DISPLAY_NAME).strip()
    if not default_display:
        default_display = _DEFAULT_COMPANION_DISPLAY_NAME
    companion_display_name = _parse_optional_display_name(data.get("companion_display_name"))
    return Persona(
        persona_id=pid,
        name=name,
        system_prompt=system_prompt,
        role_lock=role_lock,
        memory_default_on=memory_default_on,
        default_companion_display_name=default_display,
        companion_display_name=companion_display_name,
        raw=data,
    )


def apply_companion_display_name(persona: Persona, display_name: str | None) -> Persona:
    """摘要：由宿主注册页或 CLI 覆盖陪伴自称（用户指定昵称）。

    参数：
        persona: 已加载人设。
        display_name: 用户指定的自称；空白则清除覆盖，回退默认「助手一号」。

    返回值：
        更新 ``companion_display_name`` 后的新 ``Persona`` 实例。
    """
    return replace(persona, companion_display_name=_parse_optional_display_name(display_name))


def resolved_companion_display_name(persona: Persona) -> str:
    """摘要：解析当前轮应使用的陪伴自称。

    参数：
        persona: 已加载人设。

    返回值：
        用户覆盖名，或 ``default_companion_display_name``（默认「助手一号」）。
    """
    if persona.companion_display_name and persona.companion_display_name.strip():
        return persona.companion_display_name.strip()
    return persona.default_companion_display_name


def _parse_optional_display_name(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
