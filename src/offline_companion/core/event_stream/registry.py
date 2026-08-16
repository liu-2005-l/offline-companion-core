"""领域事件类型注册与基础负载校验。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_EVENT_TYPES = (
    "plan/created",
    "plan/step_started",
    "plan/step_completed",
    "plan/step_failed",
    "plan/status_changed",
    "goal/created",
    "goal/updated",
    "goal/deactivated",
    "tool/call",
    "tool/result",
    "consent/asked",
    "consent/decided",
    "model/switched",
    "model/degraded",
    "model/unavailable",
    "model/download_started",
    "model/download_progress",
    "model/download_completed",
    "model/download_failed",
    "model/download_cancelled",
    "model/verified",
    "model/verification_failed",
    "model/activated",
    "session/created",
    "session/message",
    "session/turn_start",
    "session/turn_end",
    "extension/loaded",
    "extension/unloaded",
    "extension/failed",
)


class EventTypeRegistry:
    """维护事件类型与其 schema 版本。

    参数：
        event_types: 可选的初始事件类型及版本映射。
    """

    def __init__(self, event_types: Mapping[str, int] | None = None) -> None:
        self._schema_versions: dict[str, int] = {}
        if event_types:
            for event_type, schema_version in event_types.items():
                self.register(event_type, schema_version)

    def register(self, event_type: str, schema_version: int = 1) -> None:
        """注册事件类型。

        参数：
            event_type: 事件类型名称。
            schema_version: 该类型的 schema 版本。

        Raises:
            ValueError: 类型已注册或版本无效。
        """
        if event_type in self._schema_versions:
            raise ValueError(f"事件类型已注册: {event_type}")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("事件类型必须是非空字符串")
        if not isinstance(schema_version, int) or schema_version < 1:
            raise ValueError("schema_version 必须是正整数")
        self._schema_versions[event_type] = schema_version

    def validate(self, event_type: str, payload: dict[str, Any]) -> int:
        """校验事件类型和基础负载，并返回 schema 版本。

        参数：
            event_type: 待校验的事件类型。
            payload: 待校验的事件负载。

        返回值：
            已注册事件类型的 schema 版本。

        Raises:
            ValueError: 事件类型未注册。
            TypeError: 负载不是字典。
        """
        if event_type not in self._schema_versions:
            raise ValueError(f"未知事件类型: {event_type}")
        if not isinstance(payload, dict):
            raise TypeError("事件 payload 必须是 dict")
        return self._schema_versions[event_type]

    def schema_version(self, event_type: str) -> int:
        """返回已注册事件类型的 schema 版本。"""
        if event_type not in self._schema_versions:
            raise ValueError(f"未知事件类型: {event_type}")
        return self._schema_versions[event_type]


def build_default_registry() -> EventTypeRegistry:
    """创建包含计划内全部事件类型的独立注册表。"""
    registry = EventTypeRegistry()
    for event_type in DEFAULT_EVENT_TYPES:
        registry.register(event_type)
    return registry
