from __future__ import annotations

from offline_companion.shared.messages import BaseMessage, MessageDirection
from offline_companion.shell.auto_router import AutoRouter, AutoRoutingAdapter, RoutingContext, RoutingMode
from offline_companion.shell.message_router import MessageRouter


def test_message_router_routes_registered_namespace() -> None:
    router = MessageRouter()
    events: list[str] = []

    router.register("task", lambda message: events.append(message.topic))
    router.route(
        BaseMessage(
            message_id="m-1",
            topic="task.progress",
            source="shell",
            direction=MessageDirection.INTERNAL,
        )
    )

    assert events == ["task.progress"]


def test_message_router_uses_wildcard_handler() -> None:
    router = MessageRouter()
    events: list[str] = []

    router.register_wildcard(lambda message: events.append(message.topic))
    router.route(
        BaseMessage(
            message_id="m-2",
            topic="unknown.topic",
            source="shell",
            direction=MessageDirection.INTERNAL,
        )
    )

    assert events == ["unknown.topic"]


def test_message_router_applies_auto_routing_meta() -> None:
    router = MessageRouter()
    events: list[BaseMessage] = []
    auto_router = AutoRouter(complexity_threshold=3)
    adapter = AutoRoutingAdapter(
        auto_router,
        lambda message: RoutingContext(
            query=message.topic,
            privacy_mode="local_only" if message.meta.get("local_only") else "hybrid",
            complexity=int(message.meta.get("complexity", 0)),
            cloud_cost=float(message.meta.get("cloud_cost", 0.0)),
            cloud_budget=float(message.meta.get("cloud_budget", 1.0)),
            metadata=dict(message.meta),
        ),
    )
    router.register_auto_router(adapter)
    router.register("task", lambda message: events.append(message))

    router.route(
        BaseMessage(
            message_id="m-3",
            topic="task.plan",
            source="shell",
            direction=MessageDirection.INTERNAL,
            meta={"complexity": 10, "cloud_cost": 0.2, "cloud_budget": 1.0},
        )
    )

    assert events[0].meta["auto_route"] == RoutingMode.CLOUD.value
    assert events[0].meta["auto_route_reason"] == "complexity_threshold_exceeded"
