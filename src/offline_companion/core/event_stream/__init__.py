"""事件流领域模型与事件类型注册表。"""

from .manager import StreamManager
from .persistence import EventPersistence
from .registry import DEFAULT_EVENT_TYPES, EventTypeRegistry, build_default_registry
from .stream import EventSink, EventStream
from .types import DomainEvent

__all__ = [
    "DEFAULT_EVENT_TYPES",
    "DomainEvent",
    "EventPersistence",
    "EventSink",
    "EventStream",
    "EventTypeRegistry",
    "StreamManager",
    "build_default_registry",
]
