"""??????? DTO ??????????"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any


class MessageLayer(str, Enum):
    """????????????"""

    SHELL = "shell"
    CORE = "core"
    RUNTIME = "runtime"
    PLUGIN = "plugin"
    SYSTEM = "system"


class MessageDirection(str, Enum):
    """????????"""

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


@dataclass(frozen=True)
class BaseMessage:
    """????????????"""

    message_id: str
    topic: str
    source: str
    target: str | None = None
    session_id: str = ""
    idempotency_key: str | None = None
    timeout_sec: float = 30.0
    queue_type: str = "dialog"
    direction: MessageDirection = MessageDirection.INTERNAL
    created_at: float = field(default_factory=time)
    payload: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """??????????????????????"""
        if not (self.message_id or "").strip():
            raise ValueError("message_id ????")
        topic = (self.topic or "").strip()
        if not topic:
            raise ValueError("topic ????")
        source = (self.source or "").strip()
        if not source:
            raise ValueError("source ????")
        object.__setattr__(self, "message_id", self.message_id.strip())
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "source", source)
        if self.target is not None:
            target = self.target.strip()
            object.__setattr__(self, "target", target or None)
        object.__setattr__(self, "session_id", (self.session_id or "").strip())
        if self.idempotency_key is not None:
            key = self.idempotency_key.strip()
            object.__setattr__(self, "idempotency_key", key or None)
        normalized_queue = (self.queue_type or "dialog").strip() or "dialog"
        if normalized_queue not in {"dialog", "background"}:
            raise ValueError("queue_type ??? dialog ? background")
        object.__setattr__(self, "queue_type", normalized_queue)
        object.__setattr__(self, "timeout_sec", max(0.0, float(self.timeout_sec)))

    def namespace(self) -> str:
        """????? topic ????????"""
        if "." not in self.topic:
            return self.topic
        return self.topic.split(".", 1)[0].strip()

    def is_from_layer(self, layer: MessageLayer) -> bool:
        """????? source ????????"""
        return self.source == layer.value

    def with_meta(self, **extra: Any) -> BaseMessage:
        """???????? meta ?????"""
        merged = dict(self.meta)
        merged.update(extra)
        return BaseMessage(
            message_id=self.message_id,
            topic=self.topic,
            source=self.source,
            target=self.target,
            session_id=self.session_id,
            idempotency_key=self.idempotency_key,
            timeout_sec=self.timeout_sec,
            queue_type=self.queue_type,
            direction=self.direction,
            created_at=self.created_at,
            payload=dict(self.payload),
            meta=merged,
            error=None if self.error is None else dict(self.error),
        )
