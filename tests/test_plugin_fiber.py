"""PluginFiber 状态机与依赖快照测试。"""

import asyncio

import pytest

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.lifecycle import (
    DependencyError,
    LifecycleState,
    PluginDefinition,
    PluginFiber,
)


def run(coro):
    return asyncio.run(coro)


def test_load_success_captures_required_and_optional_services() -> None:
    stream = EventStream("fiber", build_default_registry())
    services = {"required": object(), "optional": object()}
    received = []
    definition = PluginDefinition(
        id="demo",
        factory=lambda context: received.append(context) or "service",
        requires=["required"],
        optional_requires=["optional", "missing"],
        version="2.0.0",
    )
    fiber = PluginFiber(definition)

    assert run(fiber.load({"enabled": True}, services, stream)) == "service"
    assert fiber.state is LifecycleState.ACTIVE
    assert fiber.services == services
    assert received[0].plugin_id == "demo"
    assert [event.event_type for event in stream.get_events()] == ["plugin/loaded"]


def test_missing_dependency_fails_and_emits_event() -> None:
    stream = EventStream("fiber", build_default_registry())
    fiber = PluginFiber(PluginDefinition(id="demo", factory=lambda _context: None, requires=["missing"]))

    with pytest.raises(DependencyError, match="Missing required service: missing"):
        run(fiber.load({}, {}, stream))

    assert fiber.state is LifecycleState.FAILED
    assert isinstance(fiber.error, DependencyError)
    assert stream.get_events()[-1].event_type == "plugin/failed"


def test_factory_failure_rolls_back_effects_and_can_retry() -> None:
    disposed: list[str] = []
    attempts = 0

    def factory(context):
        nonlocal attempts
        context.effect.add(lambda: lambda: disposed.append("resource"))
        attempts += 1
        if attempts == 1:
            raise RuntimeError("factory failed")
        return "recovered"

    fiber = PluginFiber(PluginDefinition(id="demo", factory=factory))
    with pytest.raises(RuntimeError, match="factory failed"):
        run(fiber.load({}, {}))

    assert fiber.state is LifecycleState.FAILED
    assert disposed == ["resource"]
    assert run(fiber.load({}, {})) == "recovered"
    assert fiber.state is LifecycleState.ACTIVE


def test_config_schema_is_validated_before_factory() -> None:
    called = []

    class Config:
        def __init__(self, *, enabled: bool) -> None:
            self.enabled = enabled

        def model_dump(self) -> dict[str, bool]:
            return {"enabled": self.enabled}

    fiber = PluginFiber(
        PluginDefinition(
            id="config",
            factory=lambda context: called.append(context.config) or context.config,
            config_schema=Config,
        )
    )

    assert run(fiber.load({"enabled": True}, {})) == {"enabled": True}
    assert called == [{"enabled": True}]


def test_unload_recursively_disposes_child_and_is_idempotent() -> None:
    disposed: list[str] = []
    parent = PluginFiber(
        PluginDefinition(
            id="parent",
            factory=lambda context: context.effect.add_disposer(lambda: disposed.append("parent")) or "parent",
        )
    )
    child = PluginFiber(
        PluginDefinition(
            id="child",
            factory=lambda context: context.effect.add_disposer(lambda: disposed.append("child")) or "child",
        )
    )
    run(parent.load({}, {}))
    run(child.load({}, {}))
    parent.add_child(child)

    run(parent.unload())
    run(parent.unload())

    assert disposed == ["child", "parent"]
    assert child.state is LifecycleState.DISPOSED
    assert parent.state is LifecycleState.DISPOSED


def test_invalid_state_transitions_are_rejected() -> None:
    fiber = PluginFiber(PluginDefinition(id="demo", factory=lambda _context: None))
    run(fiber.load({}, {}))

    with pytest.raises(RuntimeError, match="Cannot load fiber"):
        run(fiber.load({}, {}))


def test_unload_emits_unloading_and_disposed_events() -> None:
    stream = EventStream("fiber-events", build_default_registry())
    fiber = PluginFiber(PluginDefinition(id="demo", factory=lambda _context: None))

    run(fiber.load({}, {}, stream))
    run(fiber.unload())

    assert [event.event_type for event in stream.get_events()] == [
        "plugin/loaded",
        "plugin/unloading",
        "plugin/disposed",
    ]


def test_unload_bounds_async_disposer_and_reaches_disposed(caplog) -> None:
    async def hanging_disposer() -> None:
        await asyncio.sleep(10)

    def factory(context):
        context.effect.add_disposer(hanging_disposer)

    fiber = PluginFiber(PluginDefinition(id="slow", factory=factory))
    run(fiber.load({}, {}))
    run(fiber.unload(grace_timeout=0.01))

    assert fiber.state is LifecycleState.DISPOSED
    assert "Plugin effect disposal exceeded" in caplog.text
    run(fiber.unload())
    with pytest.raises(RuntimeError, match="Cannot load fiber"):
        run(fiber.load({}, {}))
