"""插件 Fiber 生命周期状态机。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .context import PluginContext
from .effect_scope import EffectScope
from .types import LifecycleState, PluginDefinition

logger = logging.getLogger(__name__)


class DependencyError(RuntimeError):
    """必需插件服务缺失。"""


class PluginFiber:
    """摘要：驱动单个插件从加载、运行到释放的确定性状态机。"""

    def __init__(self, definition: PluginDefinition) -> None:
        self._definition = definition
        self._state = LifecycleState.PENDING
        self._effect: EffectScope | None = None
        self._error: Exception | None = None
        self._service: Any = None
        self._children: list[PluginFiber] = []
        self._service_snapshot: dict[str, Any] = {}
        self._event_stream: Any = None

    @property
    def state(self) -> LifecycleState:
        """返回当前生命周期状态。"""
        return self._state

    @property
    def plugin_id(self) -> str:
        """返回插件 ID。"""
        return self._definition.id

    @property
    def is_active(self) -> bool:
        """返回插件是否已激活。"""
        return self._state is LifecycleState.ACTIVE

    @property
    def error(self) -> Exception | None:
        """返回最近一次加载错误。"""
        return self._error

    @property
    def service(self) -> Any:
        """返回插件工厂创建的服务实例。"""
        return self._service

    @property
    def services(self) -> dict[str, Any]:
        """返回依赖服务快照的副本。"""
        return dict(self._service_snapshot)

    async def load(
        self,
        config: dict[str, Any],
        available_services: dict[str, Any],
        event_stream: Any = None,
    ) -> Any:
        """摘要：校验依赖并创建插件服务。"""
        if self._state not in (LifecycleState.PENDING, LifecycleState.FAILED):
            raise RuntimeError(f"Cannot load fiber {self.plugin_id} from state {self._state}")
        self._state = LifecycleState.LOADING
        self._error = None
        self._event_stream = event_stream
        try:
            missing = [
                service_id
                for service_id in self._definition.requires
                if service_id not in available_services
            ]
            if missing:
                raise DependencyError(f"Missing required service: {missing[0]}")
            validated_config = self._validate_config(config)
            self._service_snapshot = {
                service_id: available_services[service_id]
                for service_id in (*self._definition.requires, *self._definition.optional_requires)
                if service_id in available_services
            }
            self._effect = EffectScope(self.plugin_id)
            context = PluginContext(
                plugin_id=self.plugin_id,
                config=validated_config,
                services=self._service_snapshot,
                effect=self._effect,
                event_stream=event_stream,
                logger=logging.getLogger(f"plugin.{self.plugin_id}"),
            )
            self._service = self._definition.factory(context)
            self._state = LifecycleState.ACTIVE
            self._append_event("plugin/loaded", {"plugin_id": self.plugin_id, "version": self._definition.version})
            return self._service
        except Exception as exc:
            self._error = exc
            self._state = LifecycleState.FAILED
            if self._effect is not None:
                await self._effect.dispose()
            self._append_event("plugin/failed", {"plugin_id": self.plugin_id, "error": str(exc)})
            raise

    async def unload(self, grace_timeout: float = 10.0) -> None:
        """摘要：按有界流程递归释放子插件和当前插件资源。"""
        if self._state is LifecycleState.DISPOSED:
            return
        if self._state is not LifecycleState.ACTIVE:
            raise RuntimeError(f"Cannot unload fiber {self.plugin_id} from state {self._state}")
        self._state = LifecycleState.UNLOADING
        self._append_event("plugin/unloading", {"plugin_id": self.plugin_id})
        for child in self._children:
            try:
                await child.unload(grace_timeout)
            except Exception:
                logger.exception("Child fiber unload failed: %s", child.plugin_id)
        if self._effect is not None:
            try:
                await asyncio.wait_for(self._effect.dispose(), timeout=max(0.0, grace_timeout))
            except asyncio.TimeoutError:
                logger.warning("Plugin effect disposal exceeded %.1fs: %s", grace_timeout, self.plugin_id)
        self._children.clear()
        self._service_snapshot.clear()
        self._service = None
        self._state = LifecycleState.DISPOSED
        self._append_event("plugin/disposed", {"plugin_id": self.plugin_id})

    def add_child(self, child: PluginFiber) -> None:
        """摘要：注册一个由当前 Fiber 管理的子 Fiber。"""
        if child is self:
            raise ValueError("Fiber cannot be its own child")
        self._children.append(child)

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        schema = self._definition.config_schema
        if schema is None:
            return dict(config)
        validated = schema(**config)
        if hasattr(validated, "model_dump"):
            return dict(validated.model_dump())
        if hasattr(validated, "dict"):
            return dict(validated.dict())
        raise TypeError("config_schema must provide model_dump() or dict()")

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_stream is not None:
            self._event_stream.append(event_type, payload)
