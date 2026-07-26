"""???S9A ???????????????????????"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from offline_companion.shared.runtime_paths import configs_dir, dev_repo_root
from offline_companion.shared.types import (
    CapabilityTag,
    ModelRoutingDecision,
    PrivacyMode,
    TaskProfile,
)

_PRIVACY_KEYWORDS = (
    "???",
    "???",
    "???",
    "??",
    "??",
    "??",
    "??",
    "??",
    "private",
    "personal data",
)
_NETWORK_KEYWORDS = (
    "??",
    "??",
    "??",
    "???",
    "??",
    "web",
    "browser",
    "http",
)
_CODE_KEYWORDS = (
    "??",
    "??",
    "??",
    "??",
    "??",
    "python",
    "bug",
    "stack trace",
)
_REASONING_KEYWORDS = (
    "??",
    "??",
    "??",
    "??",
    "??",
    "???",
    "????",
)
_TOOL_KEYWORDS = (
    "????",
    "tool",
    "function call",
    "????",
)


@dataclass(frozen=True)
class RoutingModelSpec:
    """????????????????????"""

    name: str
    type: str
    cost_per_1k_tokens: float
    latency_per_token_ms: float
    max_tokens: int
    capabilities: tuple[CapabilityTag, ...]
    requires_consent: bool = False


@dataclass(frozen=True)
class CostEstimate:
    """????????????????????"""

    model_name: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost: float
    estimated_latency_ms: float
    capability_match: bool
    context_fits: bool
    requires_consent: bool


@dataclass(frozen=True)
class AutoRouterConfig:
    """???AutoRouter ???????"""

    complexity_threshold: int = 4
    max_cloud_cost_per_turn: float = 0.01
    default_output_tokens_chat: int = 192
    default_output_tokens_simple_qa: int = 256
    default_output_tokens_complex_reasoning: int = 512
    default_output_tokens_code_generation: int = 640
    default_output_tokens_tool_use: int = 384


class TaskProfiler:
    """????????????????"""

    def profile(self, query: str) -> TaskProfile:
        text = (query or "").strip()
        lower = text.lower()
        privacy_sensitive = any(keyword.lower() in lower for keyword in _PRIVACY_KEYWORDS)
        requires_network = any(keyword.lower() in lower for keyword in _NETWORK_KEYWORDS)
        requires_tool = any(keyword.lower() in lower for keyword in _TOOL_KEYWORDS)
        code_related = any(keyword.lower() in lower for keyword in _CODE_KEYWORDS)
        reasoning_related = any(keyword.lower() in lower for keyword in _REASONING_KEYWORDS)
        context_length = max(256, math.ceil(len(text) / 4) + 256)

        task_type = CapabilityTag.CHAT
        required_capabilities: list[CapabilityTag] = [CapabilityTag.CHAT]
        complexity = 1

        if code_related:
            task_type = CapabilityTag.CODE_GENERATION
            required_capabilities = [CapabilityTag.CHAT, CapabilityTag.CODE_GENERATION]
            complexity = 4
        elif reasoning_related:
            task_type = CapabilityTag.COMPLEX_REASONING
            required_capabilities = [CapabilityTag.CHAT, CapabilityTag.COMPLEX_REASONING]
            complexity = 4
        elif len(text) >= 120:
            task_type = CapabilityTag.SIMPLE_QA
            required_capabilities = [CapabilityTag.CHAT, CapabilityTag.SIMPLE_QA]
            complexity = 2

        if requires_tool:
            if task_type is CapabilityTag.CHAT:
                task_type = CapabilityTag.TOOL_USE
            required_capabilities.append(CapabilityTag.TOOL_USE)
            complexity = max(complexity, 4)
        if requires_network:
            complexity = max(complexity, 3)
        if privacy_sensitive:
            complexity = max(complexity, 3)
        if len(text) >= 300:
            complexity = min(5, complexity + 1)

        required_capabilities = tuple(dict.fromkeys(required_capabilities))
        return TaskProfile(
            task_type=task_type,
            complexity_score=max(1, min(5, complexity)),
            required_capabilities=required_capabilities,
            context_length=context_length,
            privacy_sensitive=privacy_sensitive,
            requires_network=requires_network,
        )


class CostPredictor:
    """????????????????????????"""

    def __init__(self, config: AutoRouterConfig | None = None) -> None:
        self._config = config or load_auto_router_config()

    def estimate(self, profile: TaskProfile, spec: RoutingModelSpec, *, query: str) -> CostEstimate:
        input_tokens = max(profile.context_length, math.ceil(len((query or '').strip()) / 4))
        output_tokens = self._default_output_tokens(profile.task_type)
        capability_match = all(capability in spec.capabilities for capability in profile.required_capabilities)
        context_fits = spec.max_tokens >= profile.context_length
        estimated_cost = ((input_tokens + output_tokens) / 1000.0) * spec.cost_per_1k_tokens
        estimated_latency_ms = spec.latency_per_token_ms * output_tokens
        return CostEstimate(
            model_name=spec.name,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            estimated_latency_ms=estimated_latency_ms,
            capability_match=capability_match,
            context_fits=context_fits,
            requires_consent=spec.requires_consent,
        )

    def _default_output_tokens(self, task_type: CapabilityTag) -> int:
        if task_type is CapabilityTag.SIMPLE_QA:
            return self._config.default_output_tokens_simple_qa
        if task_type is CapabilityTag.COMPLEX_REASONING:
            return self._config.default_output_tokens_complex_reasoning
        if task_type is CapabilityTag.CODE_GENERATION:
            return self._config.default_output_tokens_code_generation
        if task_type is CapabilityTag.TOOL_USE:
            return self._config.default_output_tokens_tool_use
        return self._config.default_output_tokens_chat


class ModelRouter:
    """???????????????????????????"""

    def __init__(
        self,
        *,
        profiler: TaskProfiler | None = None,
        predictor: CostPredictor | None = None,
        config: AutoRouterConfig | None = None,
        specs: list[RoutingModelSpec] | None = None,
    ) -> None:
        self._config = config or load_auto_router_config()
        self._profiler = profiler or TaskProfiler()
        self._predictor = predictor or CostPredictor(self._config)
        self._specs = specs if specs is not None else load_model_routing_specs()

    def route(self, query: str, *, privacy_mode: PrivacyMode) -> ModelRoutingDecision:
        profile = self._profiler.profile(query)
        estimates = [self._predictor.estimate(profile, spec, query=query) for spec in self._specs]
        local_candidates = [
            estimate for estimate, spec in zip(estimates, self._specs, strict=False)
            if spec.type == 'local' and estimate.capability_match and estimate.context_fits
        ]
        cloud_candidates = [
            estimate for estimate, spec in zip(estimates, self._specs, strict=False)
            if spec.type == 'cloud' and estimate.capability_match and estimate.context_fits
        ]
        best_local = min(local_candidates, key=lambda item: item.estimated_latency_ms, default=None)
        best_cloud = min(cloud_candidates, key=lambda item: (item.estimated_cost, item.estimated_latency_ms), default=None)
        local_fallback_candidates = [
            estimate for estimate, spec in zip(estimates, self._specs, strict=False)
            if spec.type == "local" and estimate.context_fits
        ]
        best_local_fallback = min(
            local_fallback_candidates,
            key=lambda item: (item.estimated_latency_ms, item.estimated_cost),
            default=None,
        )

        if privacy_mode is PrivacyMode.LOCAL_ONLY:
            chosen = best_local or best_local_fallback
            if chosen is None:
                return ModelRoutingDecision(
                    selected_model='',
                    fallback_model=None,
                    requires_consent=False,
                    reason='local_only_no_local_model',
                    estimated_input_tokens=0,
                    estimated_output_tokens=0,
                    estimated_cost=0.0,
                )
            return self._decision_from_estimate(
                chosen,
                fallback_model=None,
                reason='local_only_prefers_local',
                requires_consent=False,
            )

        if profile.privacy_sensitive:
            chosen = best_local or best_local_fallback
            if chosen is not None:
                return self._decision_from_estimate(
                    chosen,
                    fallback_model=best_cloud.model_name if best_cloud else None,
                    reason='privacy_sensitive_prefers_local',
                    requires_consent=False,
                )
            if best_cloud is not None:
                return self._decision_from_estimate(
                    best_cloud,
                    fallback_model=None,
                    reason='privacy_sensitive_no_local_candidate',
                    requires_consent=best_cloud.requires_consent,
                )
            return ModelRoutingDecision(
                selected_model='',
                fallback_model=None,
                requires_consent=False,
                reason='privacy_sensitive_no_candidate',
                estimated_input_tokens=0,
                estimated_output_tokens=0,
                estimated_cost=0.0,
            )

        if best_local is not None and profile.complexity_score < self._config.complexity_threshold:
            return self._decision_from_estimate(
                best_local,
                fallback_model=best_cloud.model_name if best_cloud else None,
                reason='local_candidate_satisfies_threshold',
                requires_consent=False,
            )

        if best_cloud is not None and best_cloud.estimated_cost <= self._config.max_cloud_cost_per_turn:
            return self._decision_from_estimate(
                best_cloud,
                fallback_model=(best_local or best_local_fallback).model_name if (best_local or best_local_fallback) else None,
                reason='cloud_candidate_selected',
                requires_consent=best_cloud.requires_consent,
            )

        if best_local is not None or best_local_fallback is not None:
            return self._decision_from_estimate(
                best_local or best_local_fallback,
                fallback_model=best_cloud.model_name if best_cloud else None,
                reason='fallback_to_local',
                requires_consent=False,
            )

        if best_cloud is not None:
            return self._decision_from_estimate(
                best_cloud,
                fallback_model=None,
                reason='cloud_only_candidate',
                requires_consent=best_cloud.requires_consent,
            )

        return ModelRoutingDecision(
            selected_model='',
            fallback_model=None,
            requires_consent=False,
            reason='no_candidate_available',
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            estimated_cost=0.0,
        )

    def model_type(self, model_name: str) -> str | None:
        """摘要：按模型名返回路由配置中的类型。"""
        for spec in self._specs:
            if spec.name == model_name:
                return spec.type
        return None

    def _decision_from_estimate(
        self,
        estimate: CostEstimate | None,
        *,
        fallback_model: str | None,
        reason: str,
        requires_consent: bool,
    ) -> ModelRoutingDecision:
        if estimate is None:
            return ModelRoutingDecision(
                selected_model='',
                fallback_model=fallback_model,
                requires_consent=requires_consent,
                reason='no_candidate_available',
                estimated_input_tokens=0,
                estimated_output_tokens=0,
                estimated_cost=0.0,
            )
        return ModelRoutingDecision(
            selected_model=estimate.model_name,
            fallback_model=fallback_model,
            requires_consent=requires_consent,
            reason=reason,
            estimated_input_tokens=estimate.estimated_input_tokens,
            estimated_output_tokens=estimate.estimated_output_tokens,
            estimated_cost=estimate.estimated_cost,
        )


def model_routing_config_path() -> Path:
    """??????????????????"""
    primary = configs_dir() / 'model_routing.yaml'
    if primary.is_file():
        return primary
    return dev_repo_root() / 'configs' / 'model_routing.yaml'


def auto_router_config_path() -> Path:
    """????? AutoRouter ?????????"""
    primary = configs_dir() / 'auto_router.yaml'
    if primary.is_file():
        return primary
    return dev_repo_root() / 'configs' / 'auto_router.yaml'


def load_model_routing_specs(config_path: Path | None = None) -> list[RoutingModelSpec]:
    """??????????????????????????"""
    path = config_path or model_routing_config_path()
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    models = raw.get('models') if isinstance(raw, dict) else None
    if not isinstance(models, list):
        return []
    specs: list[RoutingModelSpec] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        specs.append(
            RoutingModelSpec(
                name=str(item.get('name') or '').strip(),
                type=str(item.get('type') or '').strip(),
                cost_per_1k_tokens=float(item.get('cost_per_1k_tokens') or 0.0),
                latency_per_token_ms=float(item.get('latency_per_token_ms') or 0.0),
                max_tokens=int(item.get('max_tokens') or 0),
                capabilities=_load_capability_tags(item.get('capabilities')),
                requires_consent=bool(item.get('requires_consent', False)),
            )
        )
    return [spec for spec in specs if spec.name]


def load_auto_router_config(config_path: Path | None = None) -> AutoRouterConfig:
    """????? AutoRouter ????????????"""
    path = config_path or auto_router_config_path()
    if not path.is_file():
        return AutoRouterConfig()
    raw = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(raw, dict):
        return AutoRouterConfig()
    return AutoRouterConfig(
        complexity_threshold=int(raw.get('complexity_threshold', 4)),
        max_cloud_cost_per_turn=float(raw.get('max_cloud_cost_per_turn', 0.01)),
        default_output_tokens_chat=int(raw.get('default_output_tokens', {}).get('chat', 192)),
        default_output_tokens_simple_qa=int(raw.get('default_output_tokens', {}).get('simple_qa', 256)),
        default_output_tokens_complex_reasoning=int(raw.get('default_output_tokens', {}).get('complex_reasoning', 512)),
        default_output_tokens_code_generation=int(raw.get('default_output_tokens', {}).get('code_generation', 640)),
        default_output_tokens_tool_use=int(raw.get('default_output_tokens', {}).get('tool_use', 384)),
    )


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
