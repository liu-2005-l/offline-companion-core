"""persona_loader：人格 YAML 加载与基础校验（B1）。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from offline_companion.shared.errors import B1PersonaAssembleError
from offline_companion.shared.types import OceanVector, Persona

_DEFAULT_COMPANION_DISPLAY_NAME = "助手一号"


def load_persona_file(path: Path) -> Persona:
    """摘要：从 YAML 文件加载人格配置。

    参数:
        path: 人格 YAML 文件路径。

    返回值:
        解析后的 `Persona` 实例。

    Raises:
        B1PersonaAssembleError: 缺少必需的 `system_prompt`。
        ValueError: OCEAN 配置缺字段或数值越界。
        TypeError: OCEAN 配置类型不是映射。
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    persona_id = str(data.get("id") or path.stem)
    name = str(data.get("name") or persona_id)
    system_prompt = str(data.get("system_prompt") or "").strip()
    if not system_prompt:
        raise B1PersonaAssembleError(f"Persona {path} missing system_prompt")
    role_lock = bool(data.get("role_lock", True))
    memory_default_on = bool(data.get("memory_default_on", True))
    default_display = str(data.get("default_companion_display_name") or _DEFAULT_COMPANION_DISPLAY_NAME).strip()
    if not default_display:
        default_display = _DEFAULT_COMPANION_DISPLAY_NAME
    companion_display_name = _parse_optional_display_name(data.get("companion_display_name"))
    ocean = _parse_ocean_vector(data.get("ocean"))
    return Persona(
        persona_id=persona_id,
        name=name,
        system_prompt=system_prompt,
        role_lock=role_lock,
        memory_default_on=memory_default_on,
        default_companion_display_name=default_display,
        companion_display_name=companion_display_name,
        raw=data,
        ocean=ocean,
    )


def apply_companion_display_name(persona: Persona, display_name: str | None) -> Persona:
    """摘要：为人格应用宿主侧覆盖的陪伴者自称。"""
    return replace(persona, companion_display_name=_parse_optional_display_name(display_name))


def resolved_companion_display_name(persona: Persona) -> str:
    """摘要：解析当前轮应使用的陪伴者自称。"""
    if persona.companion_display_name and persona.companion_display_name.strip():
        return persona.companion_display_name.strip()
    return persona.default_companion_display_name


def _parse_optional_display_name(value: object) -> str | None:
    """摘要：将可选显示名规范化为空或非空字符串。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_ocean_vector(value: object) -> OceanVector | None:
    """摘要：解析 persona YAML 中的 OCEAN 五维配置。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("persona ocean must be a mapping")
    try:
        return OceanVector(
            openness=float(value["openness"]),
            conscientiousness=float(value["conscientiousness"]),
            extraversion=float(value["extraversion"]),
            agreeableness=float(value["agreeableness"]),
            neuroticism=float(value["neuroticism"]),
        )
    except KeyError as exc:
        raise ValueError(f"persona ocean missing field: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError("persona ocean values must be numbers between 0.0 and 1.0") from exc
