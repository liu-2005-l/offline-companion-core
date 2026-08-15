"""事件流领域模型与事件类型注册表。"""

from .manager import StreamManager
from .persistence import EventPersistence
from .projection import TRAJECTORY_PROJECTION, Projection, build_trajectory_projection
from .registry import DEFAULT_EVENT_TYPES, EventTypeRegistry, build_default_registry
from .stream import EventSink, EventStream
from .types import DomainEvent

__all__ = [
    "DEFAULT_EVENT_TYPES",
    "TRAJECTORY_PROJECTION",
    "DomainEvent",
    "EventPersistence",
    "EventSink",
    "EventStream",
    "EventTypeRegistry",
    "Projection",
    "StreamManager",
    "build_default_registry",
    "build_trajectory_projection",
]
