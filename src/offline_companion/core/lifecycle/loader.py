"""声明式插件加载器。"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from .config import PluginConfigEntry, PluginsConfig
from .fiber import PluginFiber
from .topo import topological_sort
from .types import PluginDefinition

logger = logging.getLogger(__name__)


class PluginLoader:
    """摘要：按 YAML 依赖拓扑管理 PluginFiber 集合。"""

    def __init__(self, config: PluginsConfig, *, event_stream: Any = None) -> None:
        self._config = config
        self._event_stream = event_stream
        self._fibers: dict[str, PluginFiber] = {}
        self._services: dict[str, Any] = {}

    @classmethod
    def from_yaml(cls, path: Path, *, event_stream: Any = None) -> PluginLoader:
        """摘要：从 YAML 构造声明式插件加载器。"""
        return cls(PluginsConfig.from_yaml(path), event_stream=event_stream)

    @property
    def fibers(self) -> dict[str, PluginFiber]:
        """返回当前 Fiber 的副本。"""
        return dict(self._fibers)

    async def load_all(self) -> dict[str, PluginFiber]:
        """摘要：按拓扑顺序加载全部启用插件，失败插件不阻断独立插件。"""
        for entry in topological_sort(self._config.plugins):
            if entry.id in self._fibers and self._fibers[entry.id].is_active:
                continue
            fiber = PluginFiber(self._definition(entry))
            self._fibers[entry.id] = fiber
            try:
                service = await fiber.load(entry.config, self._services, self._event_stream)
            except Exception:
                logger.exception("Plugin load failed: %s", entry.id)
                continue
            self._services[entry.id] = service
        return dict(self._fibers)

    async def unload_all(self) -> None:
        """摘要：按反向拓扑顺序卸载全部已加载插件。"""
        ordered = topological_sort(self._config.plugins)
        for entry in reversed(ordered):
            fiber = self._fibers.get(entry.id)
            if fiber is None or fiber.state.value != "active":
                continue
            await fiber.unload()
            self._services.pop(entry.id, None)

    async def reload(self, plugin_id: str) -> PluginFiber:
        """摘要：卸载并重新加载单个插件。"""
        entry = next((item for item in self._config.plugins if item.id == plugin_id), None)
        if entry is None or not entry.enabled:
            raise KeyError(plugin_id)
        existing = self._fibers.get(plugin_id)
        if existing is not None and existing.is_active:
            await existing.unload()
            self._services.pop(plugin_id, None)
        fiber = PluginFiber(self._definition(entry))
        self._fibers[plugin_id] = fiber
        self._services[plugin_id] = await fiber.load(entry.config, self._services, self._event_stream)
        return fiber

    def dump_config(self) -> dict[str, Any]:
        """摘要：导出配置来源与当前插件状态。"""
        return {
            "config": self._config.as_dict(),
            "plugins": [
                {
                    "id": entry.id,
                    "module": entry.module,
                    "enabled": entry.enabled,
                    "state": self._fibers.get(entry.id).state.value if entry.id in self._fibers else "pending",
                    "error": str(self._fibers[entry.id].error) if entry.id in self._fibers and self._fibers[entry.id].error else None,
                }
                for entry in self._config.plugins
            ],
        }

    @staticmethod
    def _definition(entry: PluginConfigEntry) -> PluginDefinition:
        module = importlib.import_module(entry.module)
        factory = getattr(module, "create_plugin", None)
        if not callable(factory):
            raise TypeError(f"Plugin module {entry.module!r} must expose create_plugin")
        return PluginDefinition(
            id=entry.id,
            factory=factory,
            requires=list(entry.requires),
            optional_requires=list(entry.optional_requires),
            version=entry.version,
        )
