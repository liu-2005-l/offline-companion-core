from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p2_form_preexperiment2_spec.yaml"
REDLINE_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_redline_cases.json"
L4_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_l4_baseline.yaml"


def _load_yaml(path: Path) -> dict[str, object]:
    """摘要：读取人格约束二轮形态预实验 YAML。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_generation_matrix_counts_are_mechanical() -> None:
    """摘要：哨兵、安全与风格三块矩阵必须机械合计为 338 轮。"""
    payload = _load_yaml(SPEC_PATH)
    matrix = payload["matrix"]

    sentinel = matrix["sentinel"]
    safety = matrix["safety"]
    style = matrix["style"]
    assert sentinel["generation_count"] == (
        len(sentinel["shapes"]) * sentinel["prompt_count"] * sentinel["profile_count"] * sentinel["seed_count"]
    ) == 18
    assert safety["generation_count"] == (
        len(safety["shapes"]) * safety["prompt_count"] * safety["profile_count"] * safety["seed_count"]
    ) == 192
    assert style["generation_count"] == (
        len(style["shapes"]) * style["prompt_count"] * style["profile_count"] * style["seed_count"]
    ) == 128
    assert matrix["total_generation_count"] == 18 + 192 + 128 == 338
    assert matrix["generated_outputs_per_candidate_shape"] == 48 + 32 == 80


def test_redline_panels_use_frozen_cases_and_exact_disagreement_quota() -> None:
    """摘要：十二条生成判例全部来自 P1 冻结红线，且分歧配额固定为九条。"""
    payload = _load_yaml(SPEC_PATH)
    panels = payload["case_panels"]
    cases = json.loads(REDLINE_PATH.read_text(encoding="utf-8"))["cases"]
    by_id = {case["id"]: case for case in cases}
    disagreement_ids = set(panels["disagreement_redlines"]["ids"])
    non_disagreement_ids = set(panels["non_disagreement_redlines"]["ids"])

    assert len(disagreement_ids) == 9
    assert len(non_disagreement_ids) == 3
    assert disagreement_ids.isdisjoint(non_disagreement_ids)
    assert disagreement_ids | non_disagreement_ids <= set(by_id)
    assert all("disagreement" in by_id[case_id]["challenge_tags"] for case_id in disagreement_ids)
    assert all("disagreement" not in by_id[case_id]["challenge_tags"] for case_id in non_disagreement_ids)


def test_l4_preflight_selects_one_pair_per_pattern_family() -> None:
    """摘要：L4 静态前置每个模式族恰取一对，不把静态 fixture 计入生成轮次。"""
    payload = _load_yaml(SPEC_PATH)
    selected_ids = payload["case_panels"]["l4_static_pairs"]["ids"]
    pairs = _load_yaml(L4_PATH)["pairs"]
    selected = [pair for pair in pairs if pair["id"] in selected_ids]
    all_families = {pair["family"] for pair in pairs}

    assert len(selected_ids) == len(set(selected_ids)) == 10
    assert {pair["family"] for pair in selected} == all_families
    assert len(selected) == len(all_families) == 10
    assert payload["matrix"]["static_detector_call_count"] == len(selected) * 2 == 20
    assert payload["preflight"]["l4_static_expected_recall"] == 10
    assert payload["preflight"]["l4_static_expected_false_positives"] == 0


def test_shapes_isolate_location_and_style_instruction_variables() -> None:
    """摘要：F0b/F1b 只改变示例位置，F1b/F2 只改变抽象风格指令所在域。"""
    shapes = _load_yaml(SPEC_PATH)["shapes"]

    assert shapes["F0b"]["example_set"] == shapes["F1b"]["example_set"] == "frozen_full_examples"
    assert shapes["F0b"]["history"] == "empty"
    assert shapes["F1b"]["history"] == shapes["F2"]["history"] == "full_examples_as_user_assistant_messages"
    assert shapes["F1b"]["style_instructions"] == "system"
    assert shapes["F2"]["style_instructions"] == "history_only"
    assert shapes["F1a"]["history_pair_count"] == 2
    assert shapes["F1b"]["history_pair_count"] == shapes["F2"]["history_pair_count"] == 4


def test_fresh_seeds_and_effective_decode_defaults_are_frozen() -> None:
    """摘要：二轮使用新 seeds，并显式冻结首轮实际生效的 llama-cpp 解码默认值。"""
    generation = _load_yaml(SPEC_PATH)["generation"]

    assert set(generation["seeds"]).isdisjoint(generation["previously_used_seeds"])
    assert generation["decode"] == {
        "temperature": 0.2,
        "top_p": 0.95,
        "top_k": 40,
        "min_p": 0.05,
        "typical_p": 1.0,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "repeat_penalty": 1.0,
    }
    assert generation["contract"]["pass_decode_values_explicitly"] is True


def test_copy_gate_catches_the_historical_short_prefix_failure() -> None:
    """摘要：复制 gate 必须覆盖历史样本“那就拆开看”，不能只查十字符长串。"""
    rules = _load_yaml(SPEC_PATH)["metrics"]["truncated_copy"]["rules"]
    short_rule = next(rule for rule in rules if rule["kind"] == "short_exact_prefix")

    historical_copy = "那就拆开看"
    assert len(historical_copy) >= short_rule["minimum_han_chars"]
    assert short_rule["maximum_output_tokens"] <= 16


def test_validity_gate_precedes_three_exhaustive_decision_branches() -> None:
    """摘要：哨兵失败不得进裁决，数据有效后分支必须穷尽且只选已定义载体。"""
    payload = _load_yaml(SPEC_PATH)
    decision = payload["decision"]
    branches = decision["branches"]

    assert payload["preflight"]["any_failure_invalidates_run"] is True
    assert decision["validity_precedes_branching"] is True
    assert [branch["id"] for branch in branches] == ["branch_1", "branch_2", "branch_3"]
    assert [branch["carrier"] for branch in branches] == ["F1b", "F2", "F0b"]
    assert branches[-1]["status"] == "degraded_known_risk"
    assert decision["branch_set_is_exhaustive_after_validity"] is True


def test_runtime_trace_and_logit_region_conclusion_are_explicit() -> None:
    """摘要：渲染事实源与 logit 控制边界必须按本地实际依赖版本落档。"""
    payload = _load_yaml(SPEC_PATH)
    trace = payload["trace"]
    weighting = payload["logit_region_weighting"]

    assert trace["backend"] == "llama_cpp_python_direct"
    assert trace["chat_format"] == "chat_template.default"
    assert trace["chat_template_source"] == "gguf_metadata.tokenizer.chat_template"
    assert trace["model_yaml_template_is_runtime_source"] is False
    assert weighting["available_control"] == "token_id_to_float_logit_bias"
    assert weighting["prompt_region_weighting_available"] is False
    assert weighting["recommendation"] == "do_not_use"
