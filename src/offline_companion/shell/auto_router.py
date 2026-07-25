"""auto_router：A2 自动路由策略引擎。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from offline_companion.shared.messages import BaseMessage
from offline_companion.shared.types import PrivacyMode, RoutingMode


@dataclass(frozen=True)
class RoutingContext:
    """摘要：自动路由输入上下文。"""

    query: str
    privacy_mode: str = "hybrid"
    complexity: int = 0
    cloud_cost: float = 0.0
    cloud_budget: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingDecision:
    """摘要：自动路由决策结果。"""

    mode: RoutingMode
    reason: str
    confidence: float = 1.0
    policy_blocked: bool = False
    requires_consent: bool = False
    fallback_chain: tuple[RoutingMode, ...] = ()
    selected_by: str = "rule"


class RoutingPolicy(Protocol):
    """摘要：路由硬约束策略。"""

    def decide(self, context: RoutingContext) -> RoutingDecision | None:
        """返回拦截/强制决策；None 表示放行给 AutoRouter。"""


class RouterAdvisor(Protocol):
    """摘要：可选的路由 LLM/语义建议层。"""

    def advise(self, context: RoutingContext, candidates: tuple[RoutingMode, ...]) -> RoutingDecision | None:
        """在候选路径上给出建议；None 表示不介入。"""


class DefaultRoutingPolicy:
    """摘要：最小硬约束策略。"""

    def decide(self, context: RoutingContext) -> RoutingDecision | None:
        if context.privacy_mode == PrivacyMode.LOCAL_ONLY.value:
            return RoutingDecision(
                mode=RoutingMode.LOCAL,
                reason="privacy_mode=local_only",
                policy_blocked=True,
                requires_consent=bool(context.metadata.get("requires_consent")),
                selected_by="policy",
            )
        if context.metadata.get("force_echo"):
            return RoutingDecision(
                mode=RoutingMode.ECHO,
                reason="forced_echo",
                requires_consent=bool(context.metadata.get("requires_consent")),
                selected_by="policy",
            )
        if context.metadata.get("requires_consent"):
            return RoutingDecision(
                mode=RoutingMode.LOCAL,
                reason="requires_consent",
                requires_consent=True,
                selected_by="policy",
            )
        return None


class AutoRouter:
    """摘要：规则优先的自动路由策略引擎。"""

    def __init__(
        self,
        *,
        complexity_threshold: int = 5,
        policy: RoutingPolicy | None = None,
        advisor: RouterAdvisor | None = None,
    ) -> None:
        self._complexity_threshold = complexity_threshold
        self._policy = policy or DefaultRoutingPolicy()
        self._advisor = advisor

    def decide(self, context: RoutingContext) -> RoutingDecision:
        policy_decision = self._policy.decide(context)
        if policy_decision is not None:
            policy_decision = self._with_fallback_chain(policy_decision, context)
            return policy_decision

        candidates = tuple(self.fallback_chain(context))
        advisor_decision = self._advisor.advise(context, candidates) if self._advisor is not None else None
        if advisor_decision is not None:
            return self._with_fallback_chain(advisor_decision, context)

        if context.complexity > self._complexity_threshold:
            if context.cloud_cost <= context.cloud_budget:
                return self._with_fallback_chain(
                    RoutingDecision(
                        RoutingMode.CLOUD,
                        "complexity_threshold_exceeded",
                        confidence=0.82,
                        selected_by="rule",
                    ),
                    context,
                )
            return self._with_fallback_chain(
                RoutingDecision(
                    RoutingMode.LOCAL,
                    "cloud_cost_over_budget",
                    confidence=0.95,
                    selected_by="rule",
                ),
                context,
            )

        return self._with_fallback_chain(
            RoutingDecision(
                RoutingMode.LOCAL,
                "default_local",
                confidence=0.9,
                selected_by="rule",
            ),
            context,
        )

    def fallback_chain(self, context: RoutingContext) -> list[RoutingMode]:
        """摘要：生成 Local → Cloud → Echo 的降级链。"""
        if context.privacy_mode == PrivacyMode.LOCAL_ONLY.value:
            return [RoutingMode.LOCAL]
        chain = [RoutingMode.LOCAL]
        if context.cloud_cost <= context.cloud_budget:
            chain.append(RoutingMode.CLOUD)
        chain.append(RoutingMode.ECHO)
        return chain

    def _with_fallback_chain(self, decision: RoutingDecision, context: RoutingContext) -> RoutingDecision:
        return RoutingDecision(
            mode=decision.mode,
            reason=decision.reason,
            confidence=decision.confidence,
            policy_blocked=decision.policy_blocked,
            requires_consent=decision.requires_consent,
            fallback_chain=decision.fallback_chain or tuple(self.fallback_chain(context)),
            selected_by=decision.selected_by,
        )


@dataclass
class AutoRoutingAdapter:
    """摘要：把 BaseMessage 映射为 AutoRouter 的输入上下文。"""

    router: AutoRouter
    context_factory: Callable[[BaseMessage], RoutingContext]

    def route(self, message: BaseMessage) -> RoutingDecision:
        return self.router.decide(self.context_factory(message))
