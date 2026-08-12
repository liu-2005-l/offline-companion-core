from __future__ import annotations

import pytest

from offline_companion.storage.cloud_model_repo import (
    create_cloud_model,
    get_cloud_model,
    update_cloud_model,
)


def _payload() -> dict:
    return {
        "name": "Cloud",
        "endpoint": "https://example.test/v1/chat/completions",
        "model_name": "cloud-model",
        "api_key": "sk-secret-value",
    }


def test_cloud_model_profile_persists_without_exposing_key(tmp_path) -> None:
    payload = _payload()
    payload["capability_profile"] = {
        "instruction_following": 0.8,
        "roleplay_quality": 0.9,
        "safety_sensitivity": 0.7,
        "reasoning_ability": 0.85,
        "max_context": 32768,
    }

    public = create_cloud_model(tmp_path, payload)
    stored = get_cloud_model(tmp_path, public["id"])

    assert public["api_key"] != "sk-secret-value"
    assert public["capability_profile"] == payload["capability_profile"]
    assert stored is not None
    assert stored["api_key"] == "sk-secret-value"
    assert stored["capability_profile"] == payload["capability_profile"]


def test_cloud_model_profile_rejects_invalid_values(tmp_path) -> None:
    payload = _payload()
    payload["capability_profile"] = {"roleplay_quality": 1.5}
    with pytest.raises(ValueError, match="invalid capability_profile"):
        create_cloud_model(tmp_path, payload)


def test_cloud_model_profile_is_optional_and_updateable(tmp_path) -> None:
    public = create_cloud_model(tmp_path, _payload())
    assert public["capability_profile"] is None

    updated = update_cloud_model(
        tmp_path,
        public["id"],
        {"capability_profile": {"roleplay_quality": 0.8}},
    )
    assert updated is not None
    assert updated["capability_profile"]["roleplay_quality"] == 0.8
