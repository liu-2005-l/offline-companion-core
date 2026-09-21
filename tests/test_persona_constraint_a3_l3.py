"""摘要：P3-A3 L3 纯谓词、边界与冻结样本选择测试。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from offline_companion.core.persona_constraint import (
    AUDIT_ARITHMETIC_RETRY_TAKEN,
    AUDIT_QUALITY_RETRY_TAKEN,
    L3_INVALID_EMOTION_SIGNAL,
    L3_LOW_INTENSITY_COMFORT,
    L3_LOW_INTENSITY_CORRECTION,
    L3_STANDARD_INTENSITY,
    PersonaConstraintConfigError,
    PersonaTurnSignals,
    assemble_l1_prompt,
    default_frozen_l1_mapping,
    finalize_l1_prompt,
    l3_frozen_l1_mapping,
    load_persona_constraint_assets,
    policy_from_assets,
    resolve_l3,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("signals", "expected", "trace_code"),
    [
        (PersonaTurnSignals(), L3_STANDARD_INTENSITY, "standard_missing_emotion"),
        (PersonaTurnSignals("neutral", 0.60), L3_STANDARD_INTENSITY, "standard_unlisted_emotion"),
        (PersonaTurnSignals("surprise", 0.60), L3_STANDARD_INTENSITY, "standard_unlisted_emotion"),
        (PersonaTurnSignals("sadness", 0.0), L3_STANDARD_INTENSITY, "standard_below_floor"),
        (PersonaTurnSignals("sadness", 0.4499), L3_STANDARD_INTENSITY, "standard_below_floor"),
        (PersonaTurnSignals("sadness", 0.45), L3_LOW_INTENSITY_COMFORT, "emotion_trigger"),
        (PersonaTurnSignals("sadness", 0.6999), L3_LOW_INTENSITY_COMFORT, "emotion_trigger"),
        (PersonaTurnSignals("sadness", 0.70), L3_STANDARD_INTENSITY, "standard_full_intensity"),
        (PersonaTurnSignals("sadness", 1.0), L3_STANDARD_INTENSITY, "standard_full_intensity"),
        (
            PersonaTurnSignals(audit_events=(AUDIT_ARITHMETIC_RETRY_TAKEN,)),
            L3_LOW_INTENSITY_CORRECTION,
            "audit_trigger",
        ),
        (
            PersonaTurnSignals(
                emotion_label="sadness",
                emotion_confidence=0.50,
                audit_events=(AUDIT_QUALITY_RETRY_TAKEN,),
            ),
            L3_LOW_INTENSITY_CORRECTION,
            "audit_trigger",
        ),
        (
            PersonaTurnSignals(
                emotion_label="sadness",
                emotion_confidence=0.50,
                audit_events=("audit/unknown",),
            ),
            L3_LOW_INTENSITY_COMFORT,
            "emotion_trigger",
        ),
        (
            PersonaTurnSignals(audit_events=("audit/unknown",)),
            L3_STANDARD_INTENSITY,
            "standard_missing_emotion",
        ),
    ],
)
def test_l3_truth_table_is_deterministic(
    signals: PersonaTurnSignals,
    expected: str,
    trace_code: str,
) -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    decision = resolve_l3(signals, policy_from_assets(assets))

    assert decision.result == expected
    assert decision.trace_code == trace_code
    assert decision == resolve_l3(signals, policy_from_assets(assets))


@pytest.mark.parametrize("value", [True, False, "0.5", None, float("nan"), float("inf"), -0.01, 1.01])
def test_l3_invalid_confidence_fails_closed_without_domain_event(value: object) -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    signals = PersonaTurnSignals(
        emotion_label="sadness",
        emotion_confidence=value,
        audit_events=(AUDIT_ARITHMETIC_RETRY_TAKEN,),
    )

    decision = resolve_l3(signals, policy_from_assets(assets))

    assert decision.result == L3_INVALID_EMOTION_SIGNAL
    assert decision.constraints_enabled is False
    assert decision.audit_event is None


def test_l3_low_intensity_mapping_replaces_only_the_structural_sample_for_all_presets() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    structural = {
        sample["id"]: sample
        for samples in assets.source_payloads["structural_corpus"]["structural_samples"].values()
        for sample in samples
    }

    for preset in assets.builtin_presets:
        default = default_frozen_l1_mapping(preset.persona_id, assets)
        for domain in (L3_LOW_INTENSITY_COMFORT, L3_LOW_INTENSITY_CORRECTION):
            selected = l3_frozen_l1_mapping(preset.persona_id, assets, domain)
            assert selected.dimension_dialogue_ids == default.dimension_dialogue_ids
            assert selected.levels == default.levels
            assert selected.traits == default.traits
            assert selected.structural_sample_id != default.structural_sample_id
            assert structural[selected.structural_sample_id]["trigger_domain"] == domain

            first = finalize_l1_prompt(
                assemble_l1_prompt(preset.persona_id, assets, selected),
                "测试自称",
            )
            second = finalize_l1_prompt(
                assemble_l1_prompt(preset.persona_id, assets, selected),
                "测试自称",
            )
            assert first.encode("utf-8") == second.encode("utf-8")
            assert selected.structural_sample_id not in first


def test_downgrade_source_tamper_is_rejected_by_published_hash_chain(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
    target = tmp_path / "configs" / "persona_constraint_downgrade.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    with pytest.raises(PersonaConstraintConfigError, match="source_hash_mismatch:downgrade"):
        load_persona_constraint_assets(root_override=tmp_path)
