"""插件生命周期共享类型。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import PluginContext

Cleanup = Callable[[], Any] | Callable[[], Awaitable[Any]]


class LifecycleState(StrEnum):
    """插件生命周期状态。"""

    PENDING = "pending"
    LOADING = "loading"
    ACTIVE = "active"
    FAILED = "failed"
    UNLOADING = "unloading"
    DISPOSED = "disposed"


@dataclass
class PluginDefinition:
    """摘要：描述一个待加载插件及其依赖。

    参数：
        id: 插件唯一标识。
        factory: 接收插件上下文并返回服务实例的工厂。
        config_schema: 可选配置校验类型。
        requires: 必须存在的服务 ID。
        optional_requires: 可选服务 ID。
        version: 插件版本。
    """

    id: str
    factory: Callable[[PluginContext], Any]
    config_schema: type[Any] | None = None
    requires: list[str] = field(default_factory=list)
    optional_requires: list[str] = field(default_factory=list)
    version: str = "1.0.0"
