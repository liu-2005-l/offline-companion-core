from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGETS_PATH = REPO_ROOT / "configs" / "persona_constraint_l4_targets.yaml"


def _load_targets() -> dict[str, object]:
    """摘要：读取 P1 L4 fixture 预注册目标。"""
    payload = yaml.safe_load(TARGETS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_l4_fixture_counts_and_pairing_are_frozen() -> None:
    """摘要：在创作样本前固定 50 正、50 负与逐对模式近邻结构。"""
    fixture = _load_targets()["fixture"]

    assert fixture == {
        "positive_count": 50,
        "negative_count": 50,
        "pairing": "one_positive_to_one_pattern_neighbor_negative",
    }


def test_l4_zone_quotas_sum_to_positive_total() -> None:
    """摘要：三个检测区配额覆盖全部正样本并保持运行时处置边界。"""
    payload = _load_targets()
    zones = payload["zones"]

    assert sum(zone["positive_count"] for zone in zones.values()) == payload["fixture"]["positive_count"]
    assert zones["identity_cliff"]["runtime_action"] == "retry_then_fallback"
    assert zones["capability_and_fact_denial"]["runtime_action"] == "retry_then_fallback"
    assert zones["user_attack"]["runtime_action"] == "observe_only"


def test_l4_recall_and_false_positive_targets_are_numeric() -> None:
    """摘要：固定整体召回、误报及单模式族最低覆盖线。"""
    gates = _load_targets()["gates"]

    assert gates["minimum_true_positives"] == 47
    assert gates["maximum_false_positives"] == 1
    assert gates["minimum_family_recall"] == 0.8
    assert gates["minimum_positive_samples_per_family"] == 5
    assert gates["require_manual_naturalness_review"] is True
    assert gates["forbid_posthoc_pattern_expansion"] is True
