"""事件流领域模型与事件类型注册表。"""

from .manager import StreamManager
from .registry import DEFAULT_EVENT_TYPES, EventTypeRegistry, build_default_registry
from .stream import EventStream
from .types import DomainEvent

__all__ = [
    "DEFAULT_EVENT_TYPES",
    "DomainEvent",
    "EventStream",
    "EventTypeRegistry",
    "StreamManager",
    "build_default_registry",
]
