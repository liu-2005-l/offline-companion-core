"""???A2 ????????????? S9A ????? AutoRouter?"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from offline_companion.core.provider import ModelRequest, ProviderRegistry
from offline_companion.shared.messages import BaseMessage
from offline_companion.shared.runtime_paths import configs_dir, dev_repo_root
from offline_companion.shared.types import CapabilityTag, PrivacyMode, RoutingMode


@dataclass(frozen=True)
class RoutingModelSpec:
    """??????????????????"""

    name: str
    type: str
    cost_per_1k_tokens: float
    latency_per_token_ms: float
    max_tokens: int
    capabilities: tuple[CapabilityTag, ...]
    requires_consent: bool = False


def model_routing_config_path() -> Path:
    """????????????????"""
    primary = configs_dir() / "model_routing.yaml"
    if primary.is_file():
        return primary
    return dev_repo_root() / "configs" / "model_routing.yaml"


def load_model_routing_specs(config_path: Path | None = None) -> list[RoutingModelSpec]:
    """??????????????????????????"""
    path = config_path or model_routing_config_path()
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models, list):
        return []
    specs: list[RoutingModelSpec] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        specs.append(
            RoutingModelSpec(
                name=str(item.get("name") or "").strip(),
                type=str(item.get("type") or "").strip(),
                cost_per_1k_tokens=float(item.get("cost_per_1k_tokens") or 0.0),
                latency_per_token_ms=float(item.get("latency_per_token_ms") or 0.0),
                max_tokens=int(item.get("max_tokens") or 0),
                capabilities=_load_capability_tags(item.get("capabilities")),
                requires_consent=bool(item.get("requires_consent", False)),
            )
        )
    return [spec for spec in specs if spec.name]


@dataclass(frozen=True)
class RoutingContext:
    """?????????????"""

    query: str
    privacy_mode: str = "hybrid"
    complexity: int = 0
    cloud_cost: float = 0.0
    cloud_budget: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingDecision:
    """????????????"""

    mode: RoutingMode
    reason: str
    confidence: float = 1.0
    policy_blocked: bool = False
    requires_consent: bool = False
    fallback_chain: tuple[RoutingMode, ...] = ()
    selected_by: str = "rule"


class RoutingPolicy(Protocol):
    """???????????"""

    def decide(self, context: RoutingContext) -> RoutingDecision | None:
        """????/?????None ????? AutoRouter?"""


class RouterAdvisor(Protocol):
    """???????? LLM/??????"""

    def advise(self, context: RoutingContext, candidates: tuple[RoutingMode, ...]) -> RoutingDecision | None:
        """???????????None ??????"""


class DefaultRoutingPolicy:
    """???????????"""

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
    """?????????????????"""

    def __init__(
        self,
        *,
        complexity_threshold: int = 5,
        policy: RoutingPolicy | None = None,
        advisor: RouterAdvisor | None = None,
        provider_registry: ProviderRegistry | None = None,
    ) -> None:
        self._complexity_threshold = complexity_threshold
        self._policy = policy or DefaultRoutingPolicy()
        self._advisor = advisor
        self._provider_registry = provider_registry
        self.active_model_id: str | None = None
        self.active_model_path: str | None = None

    def chat(self, request: ModelRequest) -> str:
        """摘要：解析一次 Provider 快照并执行非流式生成。

        参数：
            request: 已冻结的模型请求；必须包含 Provider ID。

        返回值：
            Provider 生成的文本。

        异常：
            RuntimeError: AutoRouter 未配置 Provider 注册表或请求缺少 Provider ID。
        """
        if self._provider_registry is None:
            raise RuntimeError("AutoRouter 未配置 ProviderRegistry")
        provider_id = request.provider_id or self.active_model_id
        if not provider_id:
            raise RuntimeError("模型请求缺少 Provider ID")
        registration = self._provider_registry.resolve(provider_id)
        return registration.provider.generate(request)

    def reload_model(self, model_id: str, path: str | Path) -> None:
        """摘要：更新自动路由当前可用的本地模型元数据。

        参数：
            model_id: 已成功加载的模型 ID。
            path: 已成功加载的 GGUF 文件路径。
        """
        self.active_model_id = model_id
        self.active_model_path = str(path)

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
        """????? Local ? Cloud ? Echo ?????"""
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
    """???? BaseMessage ??? AutoRouter ???????"""

    router: AutoRouter
    context_factory: Callable[[BaseMessage], RoutingContext]

    def route(self, message: BaseMessage) -> RoutingDecision:
        return self.router.decide(self.context_factory(message))


def _load_capability_tags(raw: object) -> tuple[CapabilityTag, ...]:
    """??????????????????????"""
    if not isinstance(raw, list):
        return ()
    tags: list[CapabilityTag] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        tags.append(CapabilityTag(text))
    return tuple(tags)
