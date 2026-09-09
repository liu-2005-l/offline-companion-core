"""摘要：P3-A2 L1 冻结映射与逐字节组装测试。"""

from __future__ import annotations

from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from offline_companion.core.persona_constraint import (
    FROZEN_MAPPING_COMMIT,
    L1_PROMPT_CHARACTER_LIMIT,
    PersonaL1AssemblyError,
    assemble_l1_prompt,
    default_frozen_l1_mapping,
    derive_levels,
    finalize_l1_prompt,
    load_persona_constraint_assets,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_DEFAULT_REFERENCES = {
    "builtin_wenrou": (
        (
            "O_mid_disagreement",
            "C_mid_disagreement",
            "E_low_joy",
            "A_high_advice",
            "N_high_comfort",
        ),
        "honesty_identity_boundary",
    ),
    "builtin_baizao": (
        (
            "O_mid_disagreement",
            "C_mid_disagreement",
            "E_mid_disagreement",
            "A_low_advice",
            "N_high_comfort",
        ),
        "honesty_evidence_gap",
    ),
    "builtin_kekao": (
        (
            "O_mid_disagreement",
            "C_high_frustration",
            "E_mid_disagreement",
            "A_mid_disagreement",
            "N_mid_disagreement",
        ),
        "honesty_capability_consent",
    ),
    "builtin_tianmei": (
        (
            "O_high_advice",
            "C_mid_disagreement",
            "E_high_joy",
            "A_high_advice",
            "N_low_comfort",
        ),
        "honesty_identity_boundary",
    ),
    "builtin_keai": (
        (
            "O_high_advice",
            "C_mid_disagreement",
            "E_high_joy",
            "A_mid_disagreement",
            "N_low_comfort",
        ),
        "honesty_evidence_gap",
    ),
}


def _dialogue_index(assets) -> dict[str, dict[str, Any]]:
    return {
        dialogue["id"]: dialogue
        for levels in assets.source_payloads["dimension_corpus"]["dimension_units"].values()
        for unit in levels.values()
        for dialogue in unit["dialogues"]
    }


def _structural_index(assets) -> dict[str, dict[str, Any]]:
    return {
        sample["id"]: sample
        for samples in assets.source_payloads["structural_corpus"]["structural_samples"].values()
        for sample in samples
    }


def _render_source_turns(sample: dict[str, Any]) -> str:
    return "\n".join(
        line
        for turn in sample["turns"]
        for line in (f"U:{turn['user']}", f"A:{turn['assistant']}")
    )


def test_t12_default_mapping_matches_frozen_883f84b_references() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)

    assert FROZEN_MAPPING_COMMIT == "883f84b"
    assert set(EXPECTED_DEFAULT_REFERENCES) == {
        preset.persona_id for preset in assets.builtin_presets
    }
    for preset in assets.builtin_presets:
        mapping = default_frozen_l1_mapping(preset.persona_id, assets)
        expected_dialogues, expected_structural = EXPECTED_DEFAULT_REFERENCES[preset.persona_id]
        assert mapping.dimension_dialogue_ids == expected_dialogues
        assert mapping.structural_sample_id == expected_structural
        assert mapping.levels == preset.levels
        assert tuple(derive_levels(preset.ocean).values()) == preset.levels


def test_t13_l1_assembly_is_byte_deterministic_for_all_presets() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)

    for preset in assets.builtin_presets:
        mapping = default_frozen_l1_mapping(preset.persona_id, assets)
        first = assemble_l1_prompt(preset.persona_id, assets, mapping)
        second = assemble_l1_prompt(preset.persona_id, assets, mapping)

        assert first == second
        assert first.text.encode("utf-8") == second.text.encode("utf-8")
        assert first.character_count == len(first.text) <= L1_PROMPT_CHARACTER_LIMIT
        assert first.manifest_sha256 == assets.manifest_sha256
        assert first.frozen_mapping_commit == "883f84b"


def test_t14_l1_text_is_exact_rendering_of_frozen_sources() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    dialogues = _dialogue_index(assets)
    structural = _structural_index(assets)

    for preset in assets.builtin_presets:
        mapping = default_frozen_l1_mapping(preset.persona_id, assets)
        result = assemble_l1_prompt(preset.persona_id, assets, mapping)
        expected_blocks = [
            _render_source_turns(dialogues[dialogue_id])
            for dialogue_id in mapping.dimension_dialogue_ids
        ]
        expected_blocks.append(_render_source_turns(structural[mapping.structural_sample_id]))
        expected_levels = ",".join(
            f"{dimension}={level}"
            for dimension, level in zip(("O", "C", "E", "A", "N"), mapping.levels, strict=True)
        )
        expected = "\n".join(
            (
                preset.base_system_prompt,
                f"档位:{expected_levels}",
                "\n\n".join(expected_blocks),
                f"标签:{','.join(mapping.traits)}",
            )
        )

        assert result.text == expected
        assert result.dimension_dialogue_ids == mapping.dimension_dialogue_ids
        assert result.structural_sample_id == mapping.structural_sample_id
        assert "{display_name}" in result.text
        assert all(block in result.text for block in expected_blocks)


def test_l1_rejects_unvalidated_persona_and_non_frozen_reference() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)

    with pytest.raises(PersonaL1AssemblyError, match="persona_l1_not_validated:custom"):
        default_frozen_l1_mapping("custom", assets)

    mapping = default_frozen_l1_mapping("builtin_wenrou", assets)
    invalid = replace(
        mapping,
        dimension_dialogue_ids=(
            "O_high_advice",
            *mapping.dimension_dialogue_ids[1:],
        ),
    )
    with pytest.raises(PersonaL1AssemblyError, match="persona_l1_dialogue_not_authorized"):
        assemble_l1_prompt(mapping.persona_id, assets, invalid)


def test_l1_trace_keeps_asset_ids_out_of_model_text() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    mapping = default_frozen_l1_mapping("builtin_tianmei", assets)

    result = assemble_l1_prompt(mapping.persona_id, assets, mapping)

    assert result.character_count == 634
    assert all(dialogue_id not in result.text for dialogue_id in result.dimension_dialogue_ids)
    assert result.structural_sample_id not in result.text


def test_l1_all_authorized_mappings_fit_burned_display_name_budget() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    display_name = "甜" * 32
    maximum = 0

    for preset in assets.builtin_presets:
        default = default_frozen_l1_mapping(preset.persona_id, assets)
        composition = assets.source_payloads["persona_compositions"]["personas"][preset.name]
        dimension_candidates = tuple(
            tuple(composition["dimension_dialogue_refs"][dimension]["dialogues"])
            for dimension in ("O", "C", "E", "A", "N")
        )
        structural_candidates = tuple(
            sample_id
            for category in ("honesty", "correction", "downgrade")
            for sample_id in composition["structural_sample_refs"].get(category, ())
        )
        for dialogue_ids in product(*dimension_candidates):
            for structural_sample_id in structural_candidates:
                mapping = replace(
                    default,
                    dimension_dialogue_ids=dialogue_ids,
                    structural_sample_id=structural_sample_id,
                )
                assembled = assemble_l1_prompt(preset.persona_id, assets, mapping)
                finalized = finalize_l1_prompt(assembled, display_name)
                maximum = max(maximum, len(finalized))
                assert finalized == finalize_l1_prompt(assembled, display_name)
                assert len(finalized) <= L1_PROMPT_CHARACTER_LIMIT

    assert maximum == 652
