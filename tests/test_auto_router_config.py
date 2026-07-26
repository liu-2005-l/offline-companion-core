from __future__ import annotations

from offline_companion.shared.types import CapabilityTag
from offline_companion.shell.auto_router import load_model_routing_specs, model_routing_config_path


def test_model_routing_config_exists() -> None:
    path = model_routing_config_path()
    assert path.is_file()


def test_load_model_routing_specs_parses_capability_tags() -> None:
    specs = load_model_routing_specs()
    assert specs
    names = {spec.name for spec in specs}
    assert "qwen2.5-1.5b-instruct-q4_k_m" in names
    assert "deepseek-v4" in names
    cloud = next(spec for spec in specs if spec.name == "deepseek-v4")
    assert cloud.requires_consent is True
    assert CapabilityTag.TOOL_USE in cloud.capabilities
