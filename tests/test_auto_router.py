from __future__ import annotations

from offline_companion.shared.messages import BaseMessage
from offline_companion.shell.auto_router import AutoRouter, AutoRoutingAdapter, RoutingContext, RoutingMode


def test_auto_router_forces_local_in_local_only_mode() -> None:
    router = AutoRouter()
    decision = router.decide(RoutingContext(query="hello", privacy_mode="local_only"))

    assert decision.mode == RoutingMode.LOCAL
    assert decision.reason == "privacy_mode=local_only"


def test_auto_router_uses_cloud_when_complex_and_budget_allows() -> None:
    router = AutoRouter(complexity_threshold=3)
    decision = router.decide(
        RoutingContext(query="complex task", complexity=5, cloud_cost=0.2, cloud_budget=1.0)
    )

    assert decision.mode == RoutingMode.CLOUD


def test_auto_router_falls_back_when_cloud_over_budget() -> None:
    router = AutoRouter(complexity_threshold=3)
    decision = router.decide(
        RoutingContext(query="complex task", complexity=5, cloud_cost=2.0, cloud_budget=1.0)
    )

    assert decision.mode == RoutingMode.LOCAL
    assert decision.reason == "cloud_cost_over_budget"


def test_auto_router_fallback_chain_includes_echo() -> None:
    router = AutoRouter()
    chain = router.fallback_chain(RoutingContext(query="hi", cloud_cost=0.2, cloud_budget=1.0))

    assert chain[0].value == "local"
    assert chain[-1].value == "echo"


def test_auto_routing_adapter_routes_message() -> None:
    router = AutoRouter()

    adapter = AutoRoutingAdapter(
        router,
        lambda message: RoutingContext(
            query=message.topic,
            privacy_mode="local_only" if message.meta.get("local_only") else "hybrid",
            complexity=int(message.meta.get("complexity", 0)),
            cloud_cost=float(message.meta.get("cloud_cost", 0.0)),
            cloud_budget=float(message.meta.get("cloud_budget", 1.0)),
            metadata=dict(message.meta),
        ),
    )

    decision = adapter.route(
        BaseMessage(
            message_id="m-1",
            topic="task.plan",
            source="shell",
            meta={"complexity": 10, "cloud_cost": 0.2, "cloud_budget": 1.0},
        )
    )

    assert decision.mode == RoutingMode.CLOUD
