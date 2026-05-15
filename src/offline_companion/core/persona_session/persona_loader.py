"""persona_loader：人设 YAML 加载与基础校验（B1）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from offline_companion.shared.types import Persona


def load_persona_file(path: Path) -> Persona:
    """摘要：从 YAML 文件加载人设。

    参数：
        path: YAML 路径。

    返回值：
        `Persona` 实例。

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
    return Persona(
        persona_id=pid,
        name=name,
        system_prompt=system_prompt,
        role_lock=role_lock,
        memory_default_on=memory_default_on,
        raw=data,
    )
