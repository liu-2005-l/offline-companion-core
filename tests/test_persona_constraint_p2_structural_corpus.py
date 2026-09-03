from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

preexperiment = importlib.import_module("run_persona_constraint_p2_form_preexperiment2")
COVERAGE_PATH = REPO_ROOT / "configs" / "persona_constraint_example_coverage.yaml"
DIMENSION_PATH = REPO_ROOT / "configs" / "persona_constraint_dimension_corpus.yaml"
STRUCTURAL_PATH = REPO_ROOT / "configs" / "persona_constraint_structural_corpus.yaml"
COMPOSITION_PATH = REPO_ROOT / "configs" / "persona_constraint_persona_compositions.yaml"
FINAL_CORPUS_PATH = REPO_ROOT / "configs" / "persona_constraint_corpus.yaml"
MAPPINGS_PATH = REPO_ROOT / "configs" / "persona_constraint_mappings.yaml"
LEXICON_PATH = REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml"
PATTERNS_PATH = REPO_ROOT / "configs" / "persona_constraint_l4_patterns.yaml"


def _load(path: Path) -> dict[str, Any]:
    """摘要：读取人格约束 P2 YAML 资产。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sample_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """摘要：把三类结构样本展开为编号索引。"""
    return {
        sample["id"]: {**sample, "category": category}
        for category, samples in payload["structural_samples"].items()
        for sample in samples
    }


def _prefix_through_han_count(text: str, required_count: int) -> str:
    """摘要：截取包含指定汉字数的真实文本前缀。"""
    count = 0
    for index, character in enumerate(text):
        if "\u4e00" <= character <= "\u9fff":
            count += 1
        if count == required_count:
            return text[: index + 1]
    raise AssertionError(f"文本不足 {required_count} 个汉字：{text}")


def test_structural_library_freezes_three_by_three_contract() -> None:
    """摘要：结构样本必须固定为三类各三条且每条为二至三轮。"""
    coverage = _load(COVERAGE_PATH)["structural_library"]
    payload = _load(STRUCTURAL_PATH)
    samples_by_category = payload["structural_samples"]
    sample_ids: list[str] = []

    assert list(samples_by_category) == coverage["categories"]
    for category in coverage["categories"]:
        samples = samples_by_category[category]
        assert len(samples) == coverage["required_samples_per_category"] == 3
        for sample in samples:
            sample_ids.append(sample["id"])
            assert len(sample["turns"]) in coverage["dialogue_turns_per_sample"]
            assert all(turn["user"] and turn["assistant"] for turn in sample["turns"])

    assert len(sample_ids) == len(set(sample_ids)) == coverage["required_sample_count"] == 9


def test_structural_samples_use_only_display_name_placeholder() -> None:
    """摘要：结构样本必须参数化 display_name 且不得写死冻结具体名字。"""
    coverage = _load(COVERAGE_PATH)["structural_library"]
    payload = _load(STRUCTURAL_PATH)
    placeholder = coverage["display_name_placeholder"]

    assert payload["display_name_policy"]["placeholder"] == placeholder
    assert payload["display_name_policy"]["literal_names_forbidden"] == coverage["literal_display_names_forbidden"]
    for sample in _sample_index(payload).values():
        text = "\n".join(value for turn in sample["turns"] for value in (turn["user"], turn["assistant"]))
        assert placeholder in text, sample["id"]
        assert all(name not in text for name in coverage["literal_display_names_forbidden"]), sample["id"]


def test_structural_assistant_text_passes_frozen_scanners() -> None:
    """摘要：结构样本入场前必须通过冻结禁用语义族与 L4 扫描。"""
    corpus = _load(STRUCTURAL_PATH)
    lexicon = _load(LEXICON_PATH)
    patterns = _load(PATTERNS_PATH)
    placeholder = corpus["display_name_policy"]["placeholder"]

    for sample in _sample_index(corpus).values():
        for turn in sample["turns"]:
            reply = turn["assistant"]
            assert preexperiment.scan_forbidden(reply, lexicon) == [], (sample["id"], reply)
            assert preexperiment.scan_l4(
                reply,
                patterns,
                display_name_present=placeholder in reply,
            )["hit"] is False, (sample["id"], reply)


def test_short_prefix_copy_gate_covers_every_structural_sample() -> None:
    """摘要：历史短复制与九条结构样本必须逐条具有可工作的复制正控。"""
    coverage = _load(COVERAGE_PATH)["structural_library"]
    corpus = _load(STRUCTURAL_PATH)
    rule = coverage["short_prefix_copy_gate"]
    historical = rule["historical_positive_control"]

    historical_verdict = preexperiment.detect_copy(
        historical,
        [f"{historical}指出不合适的部分和约束，我重做。"],
        rule["maximum_output_tokens"],
    )
    assert historical_verdict["kind"] == "short_exact_prefix"

    for sample in _sample_index(corpus).values():
        reply = sample["turns"][0]["assistant"]
        prefix = _prefix_through_han_count(reply, rule["minimum_han_characters"])
        verdict = preexperiment.detect_copy(prefix, [reply], rule["maximum_output_tokens"])
        assert verdict["kind"] == "short_exact_prefix", sample["id"]


def test_persona_compositions_match_mappings_and_all_references_exist() -> None:
    """摘要：五人格组合必须逐维匹配映射且所有语料引用真实存在。"""
    coverage = _load(COVERAGE_PATH)
    dimension_corpus = _load(DIMENSION_PATH)["dimension_units"]
    structural_index = _sample_index(_load(STRUCTURAL_PATH))
    mappings = _load(MAPPINGS_PATH)["traits"]
    personas = _load(COMPOSITION_PATH)["personas"]
    contract = coverage["persona_composition"]
    used_structural_ids: set[str] = set()

    assert list(personas) == contract["required_personas"]
    assert len(personas) == contract["required_persona_count"] == 5
    for persona_name, persona in personas.items():
        assert persona["type"] == mappings[persona_name]["type"]
        assert persona["levels"] == mappings[persona_name]["levels"]
        assert set(persona["dimension_dialogue_refs"]) == set(coverage["dimension_units"]["dimensions"])

        for dimension, reference in persona["dimension_dialogue_refs"].items():
            level = persona["levels"][dimension]
            unit = dimension_corpus[dimension][level]
            available_dialogues = {dialogue["id"] for dialogue in unit["dialogues"]}
            minimum_count = (
                contract["minimum_references_for_mid_dimension"]
                if level == "mid"
                else contract["minimum_references_for_non_mid_dimension"]
            )
            assert reference["unit"] == unit["id"]
            assert len(reference["dialogues"]) >= minimum_count
            assert set(reference["dialogues"]) <= available_dialogues

        for category, required_count in contract["required_structural_samples_per_persona"].items():
            sample_ids = persona["structural_sample_refs"][category]
            assert len(sample_ids) == required_count
            assert all(structural_index[sample_id]["category"] == category for sample_id in sample_ids)
            used_structural_ids.update(sample_ids)

        downgrade_domains = {
            structural_index[sample_id]["trigger_domain"]
            for sample_id in persona["structural_sample_refs"]["downgrade"]
        }
        assert downgrade_domains == {"low_intensity_comfort", "low_intensity_correction"}

    assert used_structural_ids == set(structural_index)


def test_registered_neighbor_pairs_keep_their_level_distances() -> None:
    """摘要：甜美/可爱与温柔/甜美必须保留 P1 登记的近邻档位差。"""
    personas = _load(COMPOSITION_PATH)["personas"]
    levels = {"low": 0, "mid": 1, "high": 2}
    sweet = personas["甜美"]["levels"]
    cute = personas["可爱"]["levels"]
    gentle = personas["温柔"]["levels"]

    assert {dimension for dimension in sweet if sweet[dimension] != cute[dimension]} == {"A"}
    assert abs(levels[sweet["A"]] - levels[cute["A"]]) == 1
    assert sweet["A"] == gentle["A"] == "high"
    assert abs(levels[sweet["E"]] - levels[gentle["E"]]) == 2


def test_persona_compositions_meet_disagreement_share() -> None:
    """摘要：每人格实际引用集合中的分歧场景占比不得低于四分之一。"""
    coverage = _load(COVERAGE_PATH)
    dimension_corpus = _load(DIMENSION_PATH)["dimension_units"]
    structural_index = _sample_index(_load(STRUCTURAL_PATH))
    personas = _load(COMPOSITION_PATH)["personas"]

    for persona_name, persona in personas.items():
        scenarios: list[str] = []
        for dimension, reference in persona["dimension_dialogue_refs"].items():
            level = persona["levels"][dimension]
            dialogue_index = {
                dialogue["id"]: dialogue["scenario"] for dialogue in dimension_corpus[dimension][level]["dialogues"]
            }
            scenarios.extend(dialogue_index[dialogue_id] for dialogue_id in reference["dialogues"])
        scenarios.extend(
            structural_index[sample_id]["scenario"]
            for sample_ids in persona["structural_sample_refs"].values()
            for sample_id in sample_ids
        )

        disagreement_share = scenarios.count("disagreement") / len(scenarios)
        assert disagreement_share >= coverage["persona_composition"]["minimum_disagreement_share"], (
            persona_name,
            disagreement_share,
        )


def test_structural_and_composition_carriers_match_branch_three() -> None:
    """摘要：结构样本和组合配置都必须保持 F0b system 内嵌载体。"""
    for path in (STRUCTURAL_PATH, COMPOSITION_PATH):
        carrier = _load(path)["carrier"]
        assert carrier["type"] == "system_embedded_dialogue_blocks"
        assert carrier["runtime_history_injection"] == "forbidden"
        assert carrier["l3_modulation"] == "primary"


def test_final_corpus_manifest_references_single_sources_without_duplication() -> None:
    """摘要：P2 YAML 终版必须只聚合事实源，不复制语料或组合内容。"""
    payload = _load(FINAL_CORPUS_PATH)
    expected_sources = {
        "mappings": "configs/persona_constraint_mappings.yaml",
        "coverage_contract": "configs/persona_constraint_example_coverage.yaml",
        "dimension_corpus": "configs/persona_constraint_dimension_corpus.yaml",
        "structural_corpus": "configs/persona_constraint_structural_corpus.yaml",
        "persona_compositions": "configs/persona_constraint_persona_compositions.yaml",
    }

    assert payload["status"] == "ta_approved"
    assert payload["sources"] == expected_sources
    assert all((REPO_ROOT / relative_path).is_file() for relative_path in expected_sources.values())
    assert not ({"dimension_units", "structural_samples", "personas"} & set(payload))
    assert payload["assembly_contract"] == {
        "dimension_resolution": "trait_level_to_dimension_unit",
        "structural_resolution": "explicit_persona_references",
        "display_name_rendering": "substitute_placeholder_at_assembly",
        "missing_reference": "configuration_error",
        "duplicate_inline_corpus": "forbidden",
        "runtime_integration_batch": "P3",
    }
    assert payload["review"] == {
        "decision": "approved",
        "reviewed_dimension_units": 15,
        "reviewed_dimension_dialogues": 30,
        "reviewed_structural_samples": 9,
        "reviewed_persona_compositions": 5,
        "runtime_generation_proof": False,
        "next_validation_batch": "P3_P4",
    }
