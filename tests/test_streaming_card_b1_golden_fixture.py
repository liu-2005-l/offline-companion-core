"""摘要：校验流式卡片 B1/B3 共享 golden fixture 的结构与覆盖面。"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "fixtures" / "streaming_cards" / "b1_partial_parse_golden.json"


def _fixture() -> dict[str, object]:
    """摘要：读取 B1/B3 共享 PartialParse golden fixture。"""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _value_paths(value: object, prefix: str = "") -> set[str]:
    """摘要：提取 golden value 中的对象键与数组索引路径。"""
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths.update(_value_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            paths.add(path)
            paths.update(_value_paths(item, path))
    return paths


def _l0_transition_count(entries: list[dict[str, object]]) -> int:
    """摘要：按 false 到 true 的状态跃迁统计 L0 触发次数。"""
    transitions = 0
    previous = False
    for entry in entries:
        current = bool(entry["l0_active"])
        if current and not previous:
            transitions += 1
        previous = current
    return transitions


def test_streaming_card_golden_fixture_has_frozen_shape() -> None:
    """摘要：共享 fixture 必须固定接口字段并保持 case id 唯一。"""
    payload = _fixture()
    cases = payload["cases"]
    chains = payload["chains"]

    assert payload["schema_version"] == 1
    assert payload["partial_parse_fields"] == ["value", "closed", "complete"]
    assert payload["l0_trigger_semantics"] == "count false-to-true transitions across a chain"
    assert isinstance(cases, list)
    assert isinstance(chains, list)
    ids = [item["id"] for item in [*cases, *chains]]
    assert len(ids) == len(set(ids))


def test_streaming_card_golden_fixture_covers_contract_risk_groups() -> None:
    """摘要：fixture 覆盖规则交互、失败、complete、扫描、单调性与完整链。"""
    payload = _fixture()
    groups = {item["group"] for item in [*payload["cases"], *payload["chains"]]}

    assert groups == {
        "rules",
        "interactions",
        "failures",
        "complete_conditions",
        "struct_scan",
        "monotonicity",
        "failure_stability",
        "end_to_end",
    }


def test_streaming_card_golden_fixture_maps_every_recovery_rule_and_interaction() -> None:
    """摘要：七类修复与两个高风险交互态都有具名样本。"""
    cases = {item["id"] for item in _fixture()["cases"]}

    assert {
        "rule_incomplete_escape",
        "rule_unclosed_string_with_comma",
        "rule_trailing_comma",
        "rule_incomplete_literal",
        "rule_incomplete_number_exponent",
        "rule_incomplete_number_sign",
        "rule_empty_value_after_colon",
        "rule_incomplete_key",
        "rule_key_missing_colon",
        "interaction_literal_and_trailing_comma",
        "interaction_array_number_exponent",
    } <= cases


def test_streaming_card_golden_fixture_expected_results_match_partial_parse_contract() -> None:
    """摘要：每个单例与链节点都提供完整 PartialParse 和 L0 期待值。"""
    payload = _fixture()
    entries = list(payload["cases"])
    for chain in payload["chains"]:
        entries.extend(chain["entries"])

    for entry in entries:
        assert isinstance(entry["buffer"], str)
        assert set(entry["expected"]) == {"value", "closed", "complete"}
        assert isinstance(entry["expected"]["closed"], list)
        assert isinstance(entry["expected"]["complete"], bool)
        assert isinstance(entry["l0_active"], bool)


def test_streaming_card_golden_fixture_keeps_failure_and_closed_filters_explicit() -> None:
    """摘要：失败统一与仅 steps[i] 输出必须有具名防回归样本。"""
    payload = _fixture()
    cases = {item["id"]: item for item in payload["cases"]}

    for case_id in (
        "failure_non_object_prefix",
        "failure_mismatched_close",
        "failure_extra_close",
    ):
        assert cases[case_id]["expected"] == {
            "value": None,
            "closed": [],
            "complete": False,
        }
    assert cases["scan_direct_step_closed"]["expected"]["closed"] == ["steps[0]"]
    assert cases["scan_nested_object_filtered"]["expected"]["closed"] == ["steps[0]"]
    assert cases["scan_non_steps_array_object_filtered"]["expected"]["closed"] == []
    assert cases["scan_mixed_other_object_filtered"]["expected"]["closed"] == []
    assert cases["scan_steps_text_does_not_trigger_l0"]["l0_active"] is False


def test_streaming_card_golden_fixture_separates_complete_conditions() -> None:
    """摘要：原文合法性、词法完整性与结构闭合三项不得混判。"""
    cases = {item["id"]: item for item in _fixture()["cases"]}

    assert cases["complete_stack_empty_but_invalid_json"]["expected"] == {
        "value": None,
        "closed": [],
        "complete": False,
    }
    assert cases["complete_lexically_complete_but_stack_open"]["expected"] == {
        "value": {"steps": []},
        "closed": [],
        "complete": False,
    }
    assert cases["complete_all_conditions"]["expected"] == {
        "value": {"steps": []},
        "closed": [],
        "complete": True,
    }


def test_streaming_card_golden_chains_cover_four_distinct_invariants() -> None:
    """摘要：四条链分别钉闭合、路径、空位与失败稳定性。"""
    chains = {item["id"]: item for item in _fixture()["chains"]}

    assert set(chains) == {
        "array_literal_path_monotonic",
        "array_empty_slot_never_creates_index",
        "failure_results_stay_none",
        "realistic_plan_prefix_sequence",
    }

    literal_paths = [
        _value_paths(entry["expected"]["value"])
        for entry in chains["array_literal_path_monotonic"]["entries"]
    ]
    assert all("a[0]" in paths for paths in literal_paths)
    assert all(before <= after for before, after in pairwise(literal_paths))

    empty_paths = [
        _value_paths(entry["expected"]["value"])
        for entry in chains["array_empty_slot_never_creates_index"]["entries"]
    ]
    assert all("a[0]" not in paths for paths in empty_paths)

    failure_entries = chains["failure_results_stay_none"]["entries"]
    assert all(
        entry["expected"] == {"value": None, "closed": [], "complete": False}
        for entry in failure_entries
    )

    plan_entries = chains["realistic_plan_prefix_sequence"]["entries"]
    closed_sets = [set(entry["expected"]["closed"]) for entry in plan_entries]
    assert all(before <= after for before, after in pairwise(closed_sets))
    assert _l0_transition_count(plan_entries) == 1
