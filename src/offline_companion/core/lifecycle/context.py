"""插件工厂运行上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .effect_scope import EffectScope


@dataclass
class PluginContext:
    """摘要：向插件工厂提供配置、服务和资源作用域。"""

    plugin_id: str
    config: dict[str, Any]
    services: dict[str, Any]
    effect: EffectScope
    event_stream: Any
    logger: Any

    def service(self, service_id: str) -> Any:
        """摘要：获取必需服务。

        参数：
            service_id: 服务唯一标识。
        返回值：
            已注册的服务实例。
        Raises:
            KeyError: 服务不存在。
        """
        if service_id not in self.services:
            raise KeyError(f"Required service '{service_id}' not available")
        return self.services[service_id]
