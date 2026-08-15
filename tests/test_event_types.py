"""DomainEvent 与事件类型注册表测试。"""

from dataclasses import FrozenInstanceError

import pytest

from offline_companion.core.event_stream import (
    DEFAULT_EVENT_TYPES,
    DomainEvent,
    EventTypeRegistry,
    build_default_registry,
)


def test_domain_event_has_default_id_and_is_frozen() -> None:
    event = DomainEvent(stream_id="session-1", event_type="session/created", payload={"x": 1})

    assert event.event_id
    assert len(event.event_id) == 32
    with pytest.raises(FrozenInstanceError):
        event.seq = 1


def test_domain_event_requires_json_serializable_dict_payload() -> None:
    with pytest.raises(TypeError):
        DomainEvent(payload=["not", "a", "dict"])
    with pytest.raises(ValueError):
        DomainEvent(payload={"bad": object()})


def test_registry_registers_schema_version_and_rejects_duplicates() -> None:
    registry = EventTypeRegistry()

    registry.register("custom/event", schema_version=2)

    assert registry.validate("custom/event", {}) == 2
    assert registry.schema_version("custom/event") == 2
    with pytest.raises(ValueError, match="已注册"):
        registry.register("custom/event")


def test_registry_rejects_unknown_type_and_non_dict_payload() -> None:
    registry = EventTypeRegistry()
    registry.register("custom/event")

    with pytest.raises(ValueError, match="未知"):
        registry.validate("missing/event", {})
    with pytest.raises(TypeError):
        registry.validate("custom/event", [])


def test_default_registry_contains_all_planned_event_types() -> None:
    registry = build_default_registry()

    assert all(registry.schema_version(event_type) == 1 for event_type in DEFAULT_EVENT_TYPES)
