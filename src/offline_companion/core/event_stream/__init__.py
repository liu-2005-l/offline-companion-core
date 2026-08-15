"""事件流领域模型与事件类型注册表。"""

from .registry import DEFAULT_EVENT_TYPES, EventTypeRegistry, build_default_registry
from .types import DomainEvent

__all__ = [
    "DEFAULT_EVENT_TYPES",
    "DomainEvent",
    "EventTypeRegistry",
    "build_default_registry",
]
