from __future__ import annotations

import json

from offline_companion.shell.auto_router import AutoRouter, RoutingContext, RoutingMode
from offline_companion.shell.router_advisor import LLMRouterAdvisor, RuleBasedRouterAdvisor


class StubCloudPost:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[object] = []

    def __call__(self, request):
        self.requests.append(request)
        from offline_companion.shared.types import CloudCompletionResponse

        return CloudCompletionResponse(text=json.dumps(self.payload), raw=self.payload)


def test_rule_based_advisor_forces_cloud() -> None:
    router = AutoRouter(advisor=RuleBasedRouterAdvisor())
    decision = router.decide(RoutingContext(query="x", metadata={"force_cloud": True}))

    assert decision.mode is RoutingMode.CLOUD
    assert decision.selected_by == "rule"


def test_llm_router_advisor_returns_valid_mode() -> None:
    stub = StubCloudPost({"mode": "cloud", "reason": "best_effort", "confidence": 0.8, "requires_consent": True})
    advisor = LLMRouterAdvisor(cloud_post=stub)
    decision = advisor.advise(RoutingContext(query="x", metadata={"requires_consent": True}), (RoutingMode.LOCAL, RoutingMode.CLOUD, RoutingMode.ECHO))

    assert decision is not None
    assert decision.mode is RoutingMode.CLOUD
    assert decision.selected_by == "llm"
    assert decision.confidence == 0.8
    assert decision.requires_consent is True


def test_policy_wins_over_advisor() -> None:
    stub = StubCloudPost({"mode": "cloud", "reason": "best_effort", "confidence": 0.7})
    advisor = LLMRouterAdvisor(cloud_post=stub)
    router = AutoRouter(advisor=advisor)
    decision = router.decide(RoutingContext(query="x", metadata={"force_echo": True, "requires_consent": True}))

    assert decision.mode is RoutingMode.ECHO
    assert decision.selected_by == "policy"
    assert decision.requires_consent is True
