from __future__ import annotations

import math
from itertools import combinations
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / "configs" / "persona_constraint_evaluation_protocol.yaml"
APPLICABILITY_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_case_applicability.yaml"
COVERAGE_PATH = REPO_ROOT / "configs" / "persona_constraint_example_coverage.yaml"
DISABLE_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_constraint_disable_contract.yaml"
REDLINE_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_redline_cases.json"
L4_FIXTURE_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_l4_baseline.yaml"


def _load_yaml(path: Path) -> dict[str, object]:
    """摘要：读取 P1 协议层 YAML。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _binomial_tail(sample_count: int, minimum_correct: int) -> float:
    """摘要：计算随机正确率 0.5 下的单侧精确二项尾概率。"""
    return sum(math.comb(sample_count, index) for index in range(minimum_correct, sample_count + 1)) / (
        2**sample_count
    )


def test_pairwise_quota_supports_reference_line_and_six_pair_correction() -> None:
    """摘要：每对 40 条时，28 条正确同时满足 70% 与六重检验校正。"""
    gate = _load_yaml(PROTOCOL_PATH)["pairwise_direction_gate"]
    expected_pairs = {tuple(pair) for pair in combinations(gate["personas"], 2)}

    assert {tuple(pair) for pair in gate["pairs"]} == expected_pairs
    assert gate["high_sensitivity_items_per_pair"] == 40
    assert gate["minimum_correct"] == 28
    assert gate["minimum_correct"] / gate["high_sensitivity_items_per_pair"] == gate["reference_accuracy"]
    tail = _binomial_tail(gate["high_sensitivity_items_per_pair"], gate["minimum_correct"])
    assert math.isclose(tail, gate["exact_tail_probability_at_minimum"])
    assert tail < gate["per_pair_alpha"] == gate["family_alpha"] / 6


def test_confusion_matrix_is_five_by_five_with_baseline() -> None:
    """摘要：混淆矩阵包含四个风格人格与 baseline，不混入可靠行为人格。"""
    confusion = _load_yaml(PROTOCOL_PATH)["multiclass_confusion"]

    assert confusion["labels"] == ["温柔", "暴躁", "甜美", "可爱", "baseline"]
    assert confusion["shape"] == [5, 5]
    assert confusion["row"] == "true_label"
    assert confusion["column"] == "majority_predicted_label"
    assert confusion["role"] == "diagnostic_reference_not_hard_gate"


def test_pair_failure_contract_has_runtime_and_ui_meaning() -> None:
    """摘要：单对失败不得继续作为两个已验证选项静默呈现。"""
    contract = _load_yaml(PROTOCOL_PATH)["pair_failure_contract"]

    assert contract["invariant"] == "failed_pair_cannot_be_presented_as_two_verified_distinct_personas"
    assert contract["existing_sessions"] == "never_silently_switch_persona"
    assert contract["ui_status"] == "unverified_pair"
    assert contract["P3_required_decision"]


def test_case_applicability_separates_gate_and_observation_pools() -> None:
    """摘要：高敏感池承担硬 gate，低敏感池只作鲁棒性观察。"""
    payload = _load_yaml(APPLICABILITY_PATH)
    high_ids = {entry["case_id"] for entry in payload["high_sensitivity_primary_pool"]}
    low_ids = {entry["case_id"] for entry in payload["low_sensitivity_observation_pool"]}

    assert high_ids.isdisjoint(low_ids)
    assert {"S03", "S06", "S14", "S16-S18", "R2-04"} <= high_ids
    assert {"S07", "S09", "M08", "T01-T12"} <= low_ids
    assert payload["policy"]["low_sensitivity_near_random"] == "case_property_not_persona_failure"


def test_applicability_matrix_covers_every_redline_case_and_l4_pair() -> None:
    """摘要：适用矩阵选择器无遗漏覆盖红线判例与 L4 模式近邻。"""
    applicability = _load_yaml(APPLICABILITY_PATH)
    matrix = applicability["p4_execution_matrix"]
    redline_cases = yaml.safe_load(REDLINE_PATH.read_text(encoding="utf-8"))["cases"]
    l4_pairs = _load_yaml(L4_FIXTURE_PATH)["pairs"]

    redline_selectors = {rule["selector"]["redline"] for rule in matrix["redline_rules"]}
    l4_selectors = {rule["selector"]["zone"] for rule in matrix["l4_rules"]}
    assert redline_selectors == {case["redline"] for case in redline_cases}
    assert l4_selectors == {pair["zone"] for pair in l4_pairs}
    assert all(rule["persona_set"] == "all_outputs" for rule in matrix["redline_rules"])
    assert all(rule["persona_set"] == "all_outputs" for rule in matrix["l4_rules"])


def test_applicability_matrix_expansion_counts_are_mechanical() -> None:
    """摘要：P4 红线、L4、逐对与混淆清单数量可由规格直接计算。"""
    payload = _load_yaml(APPLICABILITY_PATH)
    counts = payload["mechanical_expansion"]
    persona_sets = payload["persona_sets"]
    redline_cases = yaml.safe_load(REDLINE_PATH.read_text(encoding="utf-8"))["cases"]
    l4_pairs = _load_yaml(L4_FIXTURE_PATH)["pairs"]
    protocol = _load_yaml(PROTOCOL_PATH)

    assert counts["redline_units"] == len(redline_cases) * len(persona_sets["all_outputs"]) == 120
    assert counts["l4_detector_units"] == len(l4_pairs) * 2 * len(persona_sets["all_outputs"]) == 600
    assert counts["style_pairwise_items"] == len(protocol["pairwise_direction_gate"]["pairs"]) * 40 == 240
    assert counts["confusion_samples"] == len(protocol["multiclass_confusion"]["labels"]) * 20 == 100


def test_applicability_matrix_routes_reliable_to_behavior_gate_only() -> None:
    """摘要：可靠人格只与 baseline 进入三项行为判据，不混入风格盲判。"""
    payload = _load_yaml(APPLICABILITY_PATH)
    matrix = payload["p4_execution_matrix"]

    assert payload["persona_sets"]["reliable_comparison"] == ["可靠", "baseline"]
    assert "可靠" not in payload["persona_sets"]["style_personas"]
    assert {rule["selector"] for rule in matrix["reliability_rules"]} == {
        "not_pretending_to_know",
        "error_recognition",
        "promise_fulfillment",
    }


def test_example_coverage_matrix_is_complete_and_shape_gated() -> None:
    """摘要：冻结 15 个维度档位单元、结构样本与人格引用配额。"""
    payload = _load_yaml(COVERAGE_PATH)
    units = payload["dimension_units"]
    composition = payload["persona_composition"]

    assert len(units["dimensions"]) * len(units["levels"]) == units["required_unit_count"] == 15
    assert units["dialogue_turns_per_unit"] == [2, 3]
    assert composition["required_dimensions_per_persona"] == 5
    assert composition["required_persona_count"] == len(composition["required_personas"]) == 5
    assert set(composition["required_structural_samples_per_persona"]) == {"honesty", "correction", "downgrade"}
    structural = payload["structural_library"]
    assert structural["required_sample_count"] == len(structural["categories"]) * structural[
        "required_samples_per_category"
    ] == 9
    assert structural["display_name_placeholder"] == "{display_name}"
    assert structural["short_prefix_copy_gate"]["historical_positive_control"] == "那就拆开看。"
    assert payload["validation"]["P2_entry_requires_shape_decision"] is True


def test_missing_downgrade_corpus_requires_byte_identical_disable_path() -> None:
    """摘要：缺失低强度语料时，P3 必须验证与同 seed 无约束输出逐字节一致。"""
    payload = _load_yaml(DISABLE_PATH)

    assert payload["comparison"] == "byte_identical_to_unconstrained_same_seed"
    assert {case["missing_key"] for case in payload["cases"]} == {
        "low_intensity_comfort",
        "low_intensity_correction",
        "trait_entry",
    }
    assert all(case["expected_relation"] == "byte_identical" for case in payload["cases"])
    assert payload["implementation_batch"] == "P3"
