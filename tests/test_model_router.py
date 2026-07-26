from __future__ import annotations

from offline_companion.shared.types import (
    CapabilityTag,
    ModelRoutingDecision,
    PrivacyMode,
    TaskProfile,
)
from offline_companion.shell.model_router import (
    CostPredictor,
    ModelRouter,
    TaskProfiler,
    auto_router_config_path,
    load_auto_router_config,
    load_model_routing_specs,
    model_routing_config_path,
)


def test_model_routing_config_exists() -> None:
    assert model_routing_config_path().is_file()
    assert auto_router_config_path().is_file()


def test_load_model_routing_specs_parses_capability_tags() -> None:
    specs = load_model_routing_specs()
    assert specs
    cloud = next(spec for spec in specs if spec.name == "deepseek-v4")
    assert CapabilityTag.TOOL_USE in cloud.capabilities
    assert cloud.requires_consent is True


def test_load_auto_router_config() -> None:
    cfg = load_auto_router_config()
    assert cfg.complexity_threshold == 5
    assert cfg.default_output_tokens_tool_use == 384


def test_task_profiler_detects_code_and_network_requirements() -> None:
    profile = TaskProfiler().profile('search the web for this Python traceback and propose a fix')
    assert profile.task_type is CapabilityTag.CODE_GENERATION
    assert CapabilityTag.CODE_GENERATION in profile.required_capabilities
    assert profile.requires_network is True
    assert profile.complexity_score >= 4
    assert profile.context_length >= 256


def test_task_profiler_marks_privacy_sensitive() -> None:
    profile = TaskProfiler().profile('this contains private personal data and medical records')
    assert profile.privacy_sensitive is True


def test_cost_predictor_checks_context_fit() -> None:
    specs = load_model_routing_specs()
    predictor = CostPredictor()
    profile = TaskProfile(
        task_type=CapabilityTag.CHAT,
        complexity_score=2,
        required_capabilities=(CapabilityTag.CHAT,),
        context_length=20000,
        privacy_sensitive=False,
        requires_network=False,
    )
    estimate = predictor.estimate(profile, specs[0], query='plain chat')
    assert estimate.context_fits is False


def test_model_router_prefers_local_for_simple_task() -> None:
    decision = ModelRouter().route('summarize this short paragraph', privacy_mode=PrivacyMode.ALWAYS_ASK)
    assert isinstance(decision, ModelRoutingDecision)
    assert decision.selected_model == 'qwen2.5-1.5b-instruct-q4_k_m'
    assert decision.requires_consent is False


def test_model_router_selects_cloud_for_tool_use() -> None:
    decision = ModelRouter().route('use a tool to search the web and generate a plan', privacy_mode=PrivacyMode.ALWAYS_ASK)
    assert decision.selected_model == 'deepseek-v4'
    assert decision.fallback_model == 'qwen2.5-1.5b-instruct-q4_k_m'
    assert decision.requires_consent is True
    assert decision.estimated_cost > 0


def test_model_router_local_only_blocks_cloud_even_for_complex_task() -> None:
    decision = ModelRouter().route('use a tool to search the web and generate a plan', privacy_mode=PrivacyMode.LOCAL_ONLY)
    assert decision.selected_model == 'qwen2.5-1.5b-instruct-q4_k_m'
    assert decision.requires_consent is False
