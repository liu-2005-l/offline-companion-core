from __future__ import annotations

from offline_companion.shell.auto_router import AutoRouter, RoutingContext, RoutingDecision, RoutingMode
from offline_companion.shared.types import PrivacyMode


def test_policy_forces_local_only() -> None:
    router = AutoRouter()
    decision = router.decide(RoutingContext(query="x", privacy_mode=PrivacyMode.LOCAL_ONLY.value))

    assert decision.mode is RoutingMode.LOCAL
    assert decision.policy_blocked is True
    assert decision.selected_by == "policy"
    assert decision.fallback_chain == (RoutingMode.LOCAL,)


def test_policy_marks_requires_consent() -> None:
    router = AutoRouter()
    decision = router.decide(RoutingContext(query="x", metadata={"requires_consent": True}))

    assert decision.requires_consent is True
    assert decision.selected_by == "policy"
    assert decision.reason == "requires_consent"


def test_router_uses_advisor_when_policy_allows() -> None:
    class Advisor:
        def advise(self, context: RoutingContext, candidates: tuple[RoutingMode, ...]) -> RoutingDecision | None:
            return RoutingDecision(RoutingMode.CLOUD, "advisor_selected", confidence=0.66, selected_by="llm")

    router = AutoRouter(advisor=Advisor())
    decision = router.decide(RoutingContext(query="x", privacy_mode=PrivacyMode.ALWAYS_ASK.value))

    assert decision.mode is RoutingMode.CLOUD
    assert decision.selected_by == "llm"
    assert decision.fallback_chain == (RoutingMode.LOCAL, RoutingMode.CLOUD, RoutingMode.ECHO)


def test_default_rule_falls_back_to_local() -> None:
    router = AutoRouter(complexity_threshold=5)
    decision = router.decide(RoutingContext(query="x", privacy_mode=PrivacyMode.ALWAYS_ASK.value, complexity=1))

    assert decision.mode is RoutingMode.LOCAL
    assert decision.reason == "default_local"
