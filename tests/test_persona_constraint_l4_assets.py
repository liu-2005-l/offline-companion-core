from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_PATH = REPO_ROOT / "configs" / "persona_constraint_l4_patterns.yaml"
FIXTURE_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_l4_baseline.yaml"
RELIABILITY_PATH = REPO_ROOT / "configs" / "persona_constraint_reliability_rules.yaml"


def _load_yaml(path: Path) -> dict[str, object]:
    """摘要：读取并验证 YAML 顶层对象。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _verdict(text: str, display_name_present: bool) -> tuple[bool, str | None, str | None]:
    """摘要：按 P1 模式语言参考实现返回是否命中及分区。"""
    payload = _load_yaml(PATTERNS_PATH)
    for zone_name, zone in payload["zones"].items():
        for family_name, family in zone["families"].items():
            if not re.search(family["pattern"], text, flags=re.IGNORECASE):
                continue
            if family.get("exclude_pattern") and re.search(family["exclude_pattern"], text, flags=re.IGNORECASE):
                continue
            if family.get("requires_display_name_absent") and display_name_present:
                continue
            return True, zone_name, family_name
    return False, None, None


def test_l4_fixture_has_fifty_paired_pattern_neighbors() -> None:
    """摘要：固定 50 对正负样本，并保持分区与模式族配额。"""
    payload = _load_yaml(FIXTURE_PATH)
    pairs = payload["pairs"]
    zone_counts = Counter(pair["zone"] for pair in pairs)
    family_counts = Counter(pair["family"] for pair in pairs)

    assert len(pairs) == 50
    assert len({pair["id"] for pair in pairs}) == 50
    assert zone_counts == {
        "identity_cliff": 20,
        "capability_and_fact_denial": 20,
        "user_attack": 10,
    }
    assert set(family_counts.values()) == {5}
    for pair in pairs:
        assert pair["positive"]["text"]
        assert pair["negative"]["text"]


def test_l4_reference_patterns_meet_preregistered_fixture_gates() -> None:
    """摘要：参考模式对冻结正负近邻达到预注册召回与误报门线。"""
    pairs = _load_yaml(FIXTURE_PATH)["pairs"]
    true_positives = 0
    false_positives = 0
    family_hits: Counter[str] = Counter()

    for pair in pairs:
        positive = pair["positive"]
        negative = pair["negative"]
        positive_hit, positive_zone, positive_family = _verdict(
            positive["text"], bool(positive.get("display_name_present", False))
        )
        negative_hit, _, _ = _verdict(negative["text"], bool(negative.get("display_name_present", False)))
        if positive_hit and positive_zone == pair["zone"] and positive_family == pair["family"]:
            true_positives += 1
            family_hits[pair["family"]] += 1
        false_positives += int(negative_hit)

    assert true_positives >= 47
    assert false_positives <= 1
    assert min(family_hits.values()) >= 4


def test_pattern_language_keeps_three_zone_actions_distinct() -> None:
    """摘要：身份、能力事实与攻击三区保持独立运行时路由。"""
    payload = _load_yaml(PATTERNS_PATH)

    assert payload["engine"]["scan"] == "single_pass"
    assert payload["zones"]["identity_cliff"]["action"] == "retry_then_fallback"
    assert payload["zones"]["capability_and_fact_denial"]["action"] == "retry_then_fallback"
    assert payload["zones"]["user_attack"]["action"] == "observe_only"
    assert payload["decision"]["semantic_or_model_classifier"] == "explicitly_out_of_scope"


def test_reliability_rules_define_machine_human_and_merge_faces() -> None:
    """摘要：可靠三判据分别冻结机器面、人工面与合并规则。"""
    payload = _load_yaml(RELIABILITY_PATH)
    criteria = payload["criteria"]

    assert set(criteria) == {"not_pretending_to_know", "error_recognition", "promise_fulfillment"}
    for criterion in criteria.values():
        assert criterion["machine"]
        assert criterion["human"]
        assert criterion["merge"]
        assert criterion["red"]
    assert payload["reviewers"]["primary"] == "two_external_non_project_reviewers"
    assert payload["reviewers"]["tie_break"] == "third_reviewer_or_ta"
    assert payload["batch_gate"]["final"] == "machine_requirement_and_human_requirement"
