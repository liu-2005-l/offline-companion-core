"""messages：跨层消息 DTO 与消息命名空间约束。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any


class MessageLayer(str, Enum):
    """摘要：消息来源/归属层级。"""

    SHELL = "shell"
    CORE = "core"
    RUNTIME = "runtime"
    PLUGIN = "plugin"
    SYSTEM = "system"


class MessageDirection(str, Enum):
    """摘要：消息流向。"""

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


@dataclass(frozen=True)
class BaseMessage:
    """摘要：跨层统一消息结构。"""

    message_id: str
    topic: str
    source: str
    target: str | None = None
    direction: MessageDirection = MessageDirection.INTERNAL
    created_at: float = field(default_factory=time)
    payload: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """摘要：确保消息关键字段始终可用于路由与审计。"""
        if not (self.message_id or "").strip():
            raise ValueError("message_id 不能为空")
        topic = (self.topic or "").strip()
        if not topic:
            raise ValueError("topic 不能为空")
        source = (self.source or "").strip()
        if not source:
            raise ValueError("source 不能为空")
        object.__setattr__(self, "message_id", self.message_id.strip())
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "source", source)
        if self.target is not None:
            target = self.target.strip()
            object.__setattr__(self, "target", target or None)

    def namespace(self) -> str:
        """摘要：返回 topic 的命名空间前缀。"""
        if "." not in self.topic:
            return self.topic
        return self.topic.split(".", 1)[0].strip()

    def is_from_layer(self, layer: MessageLayer) -> bool:
        """摘要：判断 source 是否来自指定层。"""
        return self.source == layer.value

    def with_meta(self, **extra: Any) -> "BaseMessage":
        """摘要：生成带增量 meta 的新消息。"""
        merged = dict(self.meta)
        merged.update(extra)
        return BaseMessage(
            message_id=self.message_id,
            topic=self.topic,
            source=self.source,
            target=self.target,
            direction=self.direction,
            created_at=self.created_at,
            payload=dict(self.payload),
            meta=merged,
        )
