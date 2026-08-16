"""声明式插件配置与 YAML 解析。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class PluginConfigError(ValueError):
    """插件配置格式非法。"""


@dataclass(frozen=True)
class PluginConfigEntry:
    """摘要：声明单个插件及其依赖。"""

    id: str
    module: str
    enabled: bool = True
    requires: tuple[str, ...] = ()
    optional_requires: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"

    @classmethod
    def from_mapping(cls, raw: Any) -> PluginConfigEntry:
        """摘要：从映射严格构造插件配置。"""
        if not isinstance(raw, dict):
            raise PluginConfigError("plugin entry must be a mapping")
        allowed = {"id", "module", "enabled", "requires", "optional_requires", "config", "version"}
        unknown = set(raw) - allowed
        if unknown:
            raise PluginConfigError(f"unknown plugin fields: {sorted(unknown)}")
        plugin_id = raw.get("id")
        module = raw.get("module")
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise PluginConfigError("plugin id must be a non-empty string")
        if not isinstance(module, str) or not module.strip():
            raise PluginConfigError(f"plugin {plugin_id!r} module must be a non-empty string")
        requires = _string_tuple(raw.get("requires", []), "requires", plugin_id)
        optional_requires = _string_tuple(raw.get("optional_requires", []), "optional_requires", plugin_id)
        config = raw.get("config", {})
        if not isinstance(config, dict):
            raise PluginConfigError(f"plugin {plugin_id!r} config must be a mapping")
        return cls(
            id=plugin_id.strip(),
            module=module.strip(),
            enabled=bool(raw.get("enabled", True)),
            requires=requires,
            optional_requires=optional_requires,
            config=dict(config),
            version=str(raw.get("version", "1.0.0")),
        )


@dataclass(frozen=True)
class PluginsConfig:
    """摘要：声明式插件配置文件。"""

    schema_version: int
    plugins: tuple[PluginConfigEntry, ...]

    @classmethod
    def from_mapping(cls, raw: Any) -> PluginsConfig:
        """摘要：从映射严格构造配置文件。"""
        if not isinstance(raw, dict):
            raise PluginConfigError("plugins config must be a mapping")
        unknown = set(raw) - {"schema_version", "plugins"}
        if unknown:
            raise PluginConfigError(f"unknown config fields: {sorted(unknown)}")
        schema_version = raw.get("schema_version")
        if not isinstance(schema_version, int) or schema_version < 1:
            raise PluginConfigError("schema_version must be a positive integer")
        entries = raw.get("plugins")
        if not isinstance(entries, list):
            raise PluginConfigError("plugins must be a list")
        parsed = tuple(PluginConfigEntry.from_mapping(entry) for entry in entries)
        ids = [entry.id for entry in parsed]
        if len(ids) != len(set(ids)):
            raise PluginConfigError("plugin ids must be unique")
        return cls(schema_version=schema_version, plugins=parsed)

    @classmethod
    def from_yaml(cls, path: Path) -> PluginsConfig:
        """摘要：读取并解析 UTF-8 YAML 配置。"""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise PluginConfigError(f"failed to read plugin config: {path}") from exc
        return cls.from_mapping(raw or {})

    def as_dict(self) -> dict[str, Any]:
        """返回可序列化配置。"""
        return {
            "schema_version": self.schema_version,
            "plugins": [
                {
                    "id": entry.id,
                    "module": entry.module,
                    "enabled": entry.enabled,
                    "requires": list(entry.requires),
                    "optional_requires": list(entry.optional_requires),
                    "config": dict(entry.config),
                    "version": entry.version,
                }
                for entry in self.plugins
            ],
        }


def _string_tuple(value: Any, field_name: str, plugin_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise PluginConfigError(f"plugin {plugin_id!r} {field_name} must be a list of strings")
    return tuple(item.strip() for item in value)
