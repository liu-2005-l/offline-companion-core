from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

runner = importlib.import_module("run_persona_constraint_p2_form_preexperiment2")
SPEC = yaml.safe_load(
    (REPO_ROOT / "fixtures/persona_constraints/p2_form_preexperiment2_spec.yaml").read_text(encoding="utf-8")
)
EXAMPLES = json.loads((REPO_ROOT / SPEC["source_assets"]["example_fixture"]).read_text(encoding="utf-8"))
REDLINES = json.loads((REPO_ROOT / SPEC["source_assets"]["redline_fixture"]).read_text(encoding="utf-8"))
LEXICON = yaml.safe_load((REPO_ROOT / SPEC["source_assets"]["lexicon"]).read_text(encoding="utf-8"))
PATTERNS = yaml.safe_load((REPO_ROOT / SPEC["source_assets"]["l4_patterns"]).read_text(encoding="utf-8"))
L4_FIXTURE = yaml.safe_load((REPO_ROOT / SPEC["source_assets"]["l4_baseline"]).read_text(encoding="utf-8"))
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "persona_constraints" / "p2_form_preexperiment2"


def test_static_preflight_passes_frozen_examples_and_all_pattern_families() -> None:
    """摘要：冻结四组示例、对比度与十个 L4 模式族前置检查全绿。"""
    payload = runner.static_preflight(SPEC, EXAMPLES, LEXICON, PATTERNS, L4_FIXTURE)

    assert payload["passed"] is True
    assert len(payload["examples"]) == 4
    assert payload["contrast"]["E"]["high"] > payload["contrast"]["E"]["low"]
    assert payload["contrast"]["A"]["high"] > payload["contrast"]["A"]["low"]
    assert payload["l4"]["true_positives"] == 10
    assert payload["l4"]["false_positives"] == 0


def test_shape_messages_keep_frozen_content_and_role_boundaries() -> None:
    """摘要：F0b/F1b 内容一致且位置不同，F2 不保留抽象风格指令。"""
    f0b = runner.build_messages(EXAMPLES, "F0b", "E_high_A_low", "当前问题")
    f1b = runner.build_messages(EXAMPLES, "F1b", "E_high_A_low", "当前问题")
    f2 = runner.build_messages(EXAMPLES, "F2", "E_high_A_low", "当前问题")
    assistant_examples = runner.injected_assistant_examples(EXAMPLES, "F1b", "E_high_A_low")

    assert len(assistant_examples) == 4
    assert all(example in f0b[0]["content"] for example in assistant_examples)
    assert [message["content"] for message in f1b if message["role"] == "assistant"] == assistant_examples
    assert "E 维要求" in f1b[0]["content"]
    assert "E 维要求" not in f2[0]["content"]
    assert f1b[1:] == f2[1:]


def test_matrix_expansion_matches_preregistered_338_rounds() -> None:
    """摘要：runner 展开数与机器规格的 18+192+128 完全一致。"""
    sentinel = sum(
        len(runner.matrix_rows(SPEC, EXAMPLES, REDLINES, stage="sentinel", seed=seed))
        for seed in SPEC["generation"]["seeds"]
    )
    candidates = sum(
        len(runner.matrix_rows(SPEC, EXAMPLES, REDLINES, stage="candidate", seed=seed))
        for seed in SPEC["generation"]["seeds"]
    )

    assert sentinel == 18
    assert candidates == 320
    assert sentinel + candidates == SPEC["matrix"]["total_generation_count"] == 338


def test_short_copy_positive_control_catches_historical_failure() -> None:
    """摘要：短前缀复制正控必须抓住“那就拆开看”。"""
    verdict = runner.detect_copy("那就拆开看。", ["那就拆开看。指出不靠谱的部分和约束，我重做。"], 6)

    assert verdict == {"hit": True, "kind": "short_exact_prefix", "matched_chars": 6}


def test_l4_display_name_exception_and_expected_family_are_preserved() -> None:
    """摘要：通用 AI 自称仅在当前 display_name 在场时放行。"""
    cliff = runner.scan_l4("作为AI助手，我会继续陪你。", PATTERNS, display_name_present=False)
    allowed = runner.scan_l4("作为AI助手，我是小岚。", PATTERNS, display_name_present=True)

    assert cliff["zone"] == "identity_cliff"
    assert cliff["family"] == "generic_ai_self_reference"
    assert allowed["hit"] is False


def test_human_review_quota_is_four_rows_per_candidate_shape() -> None:
    """摘要：人工自然度抽样固定为每形态一判例、双 profile、双 seed 共四条。"""
    candidate_rows = [
        row
        for seed in SPEC["generation"]["seeds"]
        for row in runner.matrix_rows(SPEC, EXAMPLES, REDLINES, stage="candidate", seed=seed)
    ]
    sample = [row for row in candidate_rows if row["stage"] == "safety" and row["case_id"] == "R1-04"]

    assert len(sample) == 16
    for shape in runner.CANDIDATE_SHAPES:
        assert sum(row["shape"] == shape for row in sample) == 4


def test_human_review_references_exact_raw_lines_and_fails_all_shapes() -> None:
    """摘要：人工审读索引必须指向原始行，且四形态结论与逐条红项一致。"""
    raw_rows = [json.loads(line) for line in (ARTIFACT_DIR / "raw.jsonl").read_text(encoding="utf-8").splitlines()]
    review = json.loads((ARTIFACT_DIR / "human_review.json").read_text(encoding="utf-8"))

    assert len(review["rows"]) == 16
    for item in review["rows"]:
        assert raw_rows[item["raw_line"] - 1]["row_id"] == item["row_id"]
    for shape in runner.CANDIDATE_SHAPES:
        shape_rows = [item for item in review["rows"] if f"-{shape}-" in item["row_id"]]
        assert review["summary"][shape]["red"] == sum(item["verdict"] == "red" for item in shape_rows)
        assert review["summary"][shape]["passed"] is False


def test_decision_uses_branch_three_without_granting_runtime_acceptance() -> None:
    """摘要：F1b/F2 自动与人工门均失败时，只解除 P2 语料创作入口。"""
    decision = json.loads((ARTIFACT_DIR / "decision.json").read_text(encoding="utf-8"))

    assert decision["run_valid"] is True
    assert decision["selected_branch"] == "branch_3"
    assert decision["carrier"] == "F0b"
    assert decision["carrier_status"] == "degraded_known_risk"
    assert decision["p2_entry"] == "unblocked_for_corpus_authoring"
    assert set(decision["not_granted"]) == {"runtime_acceptance", "P4_acceptance", "release_acceptance"}
