"""auto_router：A2 自动路由策略引擎最小实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from offline_companion.shared.messages import BaseMessage


class RoutingMode(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"
    ECHO = "echo"


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


class AutoRouter:
    """摘要：规则优先的自动路由策略引擎。

    说明：
        当前实现遵循最小策略：
        1. local_only 强制本地；
        2. 复杂度高且预算允许时可走云端；
        3. 云端成本超预算时降级；
        4. 其余情况默认本地。
    """

    def __init__(self, *, complexity_threshold: int = 5) -> None:
        self._complexity_threshold = complexity_threshold

    def decide(self, context: RoutingContext) -> RoutingDecision:
        if context.privacy_mode == "local_only":
            return RoutingDecision(RoutingMode.LOCAL, "privacy_mode=local_only")

        if context.complexity > self._complexity_threshold:
            if context.cloud_cost <= context.cloud_budget:
                return RoutingDecision(RoutingMode.CLOUD, "complexity_threshold_exceeded")
            return RoutingDecision(RoutingMode.LOCAL, "cloud_cost_over_budget")

        if context.metadata.get("force_echo"):
            return RoutingDecision(RoutingMode.ECHO, "forced_echo")

        return RoutingDecision(RoutingMode.LOCAL, "default_local")

    def fallback_chain(self, context: RoutingContext) -> list[RoutingMode]:
        """摘要：生成 Local → Cloud → Echo 的降级链。"""
        if context.privacy_mode == "local_only":
            return [RoutingMode.LOCAL]
        chain = [RoutingMode.LOCAL]
        if context.cloud_cost <= context.cloud_budget:
            chain.append(RoutingMode.CLOUD)
        chain.append(RoutingMode.ECHO)
        return chain


@dataclass
class AutoRoutingAdapter:
    """摘要：把 BaseMessage 映射为 AutoRouter 的输入上下文。"""

    router: AutoRouter
    context_factory: Callable[[BaseMessage], RoutingContext]

    def route(self, message: BaseMessage) -> RoutingDecision:
        return self.router.decide(self.context_factory(message))
