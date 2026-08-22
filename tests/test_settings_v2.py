from __future__ import annotations

import json

from offline_companion.storage.settings_store import (
    get_all,
    get_module,
    load_settings,
    patch_module,
)


def test_legacy_settings_migrate_to_nested_v2_and_backup(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "dark", "privacy_mode": "LOCAL_ONLY", "active_model_id": "m1"}), encoding="utf-8")

    settings = get_all(tmp_path)

    assert settings["schema_version"] == 2
    assert settings["appearance"]["theme"] == "dark"
    assert settings["privacy"]["privacy_mode"] == "LOCAL_ONLY"
    assert settings["model"]["local_model_id"] == "m1"
    assert (tmp_path / "settings.v1.bak.json").exists()


def test_patch_module_deep_merges_without_losing_siblings(tmp_path) -> None:
    patch_module(tmp_path, "appearance", {"accent": {"color": "#000000"}})

    appearance = get_module(tmp_path, "appearance")

    assert appearance["accent"]["color"] == "#000000"
    assert appearance["accent"]["hover"] == "#2563eb"
    assert appearance["corner_radius"] == 12


def test_legacy_aliases_keep_existing_callers_working(tmp_path) -> None:
    patch_module(tmp_path, "behavior", {"idle_think_enabled": False})

    settings = load_settings(tmp_path)

    assert settings["idle_think_enabled"] is False
    assert settings["behavior"]["idle_think_enabled"] is False


def test_decomposition_learning_defaults_on_and_keeps_legacy_alias(tmp_path) -> None:
    settings = load_settings(tmp_path)

    assert settings["behavior"]["decomp_learning_enabled"] is True
    assert settings["decomp_learning_enabled"] is True
