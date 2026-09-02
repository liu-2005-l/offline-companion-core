from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "configs" / "persona_constraint_downgrade.yaml"
LEXICON_PATH = REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml"
FIXTURE_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_downgrade_boundaries.yaml"


def _load_yaml(path: Path) -> dict[str, object]:
    """摘要：读取降档规格相关 YAML。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _resolve(case: dict[str, object], spec: dict[str, object]) -> str:
    """摘要：按冻结阈值、事件白名单与优先级解析降档结果。"""
    audit_event = case.get("audit_event")
    if audit_event in spec["audit_events"]["whitelist"]:
        return spec["resolution"]["audit_trigger_result"]
    emotion = spec["emotion_context"]
    confidence = float(case["confidence"])
    if case["emotion"] not in emotion["empathy_sensitive_labels"]:
        return spec["resolution"]["normal_result"]
    if confidence < float(emotion["accepted_confidence_floor"]):
        return spec["resolution"]["normal_result"]
    if confidence < float(emotion["full_intensity_threshold"]):
        return spec["resolution"]["emotion_trigger_result"]
    return spec["resolution"]["normal_result"]


def test_downgrade_thresholds_and_boundaries_are_preregistered() -> None:
    """摘要：固定 0.45 接受线、0.70 完整强度线及边界归属。"""
    spec = _load_yaml(SPEC_PATH)
    emotion = spec["emotion_context"]

    assert emotion["accepted_confidence_floor"] == 0.45
    assert emotion["full_intensity_threshold"] == 0.70
    assert emotion["boundary_rule"] == "confidence_gte_0_70_is_full"
    assert emotion["recalibration"].startswith("P4_")


def test_audit_trigger_uses_explicit_whitelist_only() -> None:
    """摘要：技术纠错仅由三个白名单审计事件触发。"""
    spec = _load_yaml(SPEC_PATH)

    assert set(spec["audit_events"]["whitelist"]) == {
        "audit/arithmetic_retry_taken",
        "audit/arithmetic_warning_appended",
        "audit/quality_retry_taken",
    }
    assert "unknown_audit_event" in spec["audit_events"]["non_triggering"]
    assert spec["audit_events"]["implementation_note"].endswith("not_yet_in_DEFAULT_EVENT_TYPES")


def test_downgrade_boundary_fixture_is_deterministic() -> None:
    """摘要：边界、优先级和未知事件判例均得到唯一结果。"""
    spec = _load_yaml(SPEC_PATH)
    cases = _load_yaml(FIXTURE_PATH)["cases"]

    assert len(cases) == 12
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert _resolve(case, spec) == case["expected"]


def test_every_trait_has_both_low_intensity_corpora() -> None:
    """摘要：每个人格都具备共情与纠错低强度档，防止触发后空转。"""
    spec = _load_yaml(SPEC_PATH)
    traits = _load_yaml(LEXICON_PATH)["traits"]
    contract = spec["corpus_contract"]

    for trait in traits.values():
        for key in contract["required_keys_per_trait"]:
            assert len(trait[key]) >= contract["minimum_examples_per_key"]
