from __future__ import annotations

import hashlib
import importlib
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

runner = importlib.import_module("run_persona_constraint_p3_0_l2_confirmation_stage1")
SPEC_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p3_0_l2_confirmation_stage1_spec.yaml"
SPEC = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
SCREENING_SPEC, SOURCES = runner.load_context(SPEC)
VERDICT = runner._load_json(REPO_ROOT / SPEC["trace"]["balanced_screening_verdict"])
OUTPUT_DIR = REPO_ROOT / "artifacts" / "persona_constraints" / "p3_0_l2_confirmation_stage1"
COMPLETED_PATH = OUTPUT_DIR / "blind_review_completed.json"
KEY_PATH = OUTPUT_DIR / "blind_review_key.json"
STAGE1_VERDICT_PATH = OUTPUT_DIR / "blind_review_verdict.json"
NO_EFFECT_SPEC_PATH = (
    REPO_ROOT / "fixtures" / "persona_constraints" / "p3_0_l2_no_effect_closure_spec.yaml"
)


def test_stage1_preregisters_exact_32_of_22_gate() -> None:
    """摘要：第一段必须固定四格各八对与二十二胜门线。"""
    assert SPEC["design"]["target_count"] == 4
    assert SPEC["design"]["pairs_per_target"] == 8
    assert SPEC["design"]["pair_count"] == 32
    assert SPEC["design"]["output_count"] == 64
    assert SPEC["decision"]["minimum_successes"] == 22
    assert SPEC["decision"]["exact_one_sided_p_at_gate"] < 0.05
    assert SPEC["decision"]["exact_one_sided_p_below_gate"] > 0.05


def test_stage1_prompts_and_seeds_are_fresh_and_leakage_free() -> None:
    """摘要：确认第一段不得复用 screening prompt、seed 或注入示例问句。"""
    result = runner.prompt_preflight(SPEC, SCREENING_SPEC, SOURCES["dimension_corpus"])

    assert result["passed"] is True
    assert all(result["checks"].values())
    assert len(result["comparisons"]) == 24
    assert all(item["passed"] for item in result["comparisons"])


def test_stage1_matrix_has_four_targets_eight_pairs_and_two_outputs() -> None:
    """摘要：矩阵必须机械展开为四格各八个 candidate-baseline 配对。"""
    rows = runner.matrix_rows(SPEC, SCREENING_SPEC, VERDICT)

    assert len(rows) == 64
    counts = Counter((row["target"], row["prompt_id"]) for row in rows)
    assert set(counts.values()) == {2}
    assert len(counts) == 32
    target_counts = Counter(row["target"] for row in rows if row["arm_id"] != "baseline")
    assert target_counts == Counter({"C_low": 8, "A_low": 8, "A_high": 8, "N_low": 8})


def test_stage1_blind_packet_is_four_four_per_target_without_identity_leaks() -> None:
    """摘要：脱敏包必须逐格 candidate 左右各四且不暴露参数身份。"""
    rows = runner.matrix_rows(SPEC, SCREENING_SPEC, VERDICT)
    fake_rows = [
        {
            **row,
            "reply": f"reply-{row['row_id']}",
            "automatic_gate": {
                "forbidden": True,
                "l4_retry_then_fallback": True,
                "copy": True,
                "finish": True,
                "nonempty": True,
                "complete_terminal": True,
            },
            "automatic_passed": True,
        }
        for row in rows
    ]

    packet, key = runner.build_blind_review(SPEC, SOURCES["dimension_corpus"], fake_rows)

    assert len(packet["rows"]) == len(key["rows"]) == 32
    assert all("arm_id" not in item and "candidate_side" not in item for item in packet["rows"])
    placements = Counter((item["target"], item["candidate_side"]) for item in key["rows"])
    for target in SPEC["selected_candidates"]:
        assert placements[(target, "left")] == 4
        assert placements[(target, "right")] == 4


def test_completed_review_was_sealed_before_key_access() -> None:
    """摘要：外部盲判完成件必须完整、合法并与独立哈希封条一致。"""
    packet = runner._load_json(OUTPUT_DIR / "blind_review_packet.json")
    completed = runner._load_json(COMPLETED_PATH)
    sealed_hash = (OUTPUT_DIR / "blind_review_completed.sha256").read_text(encoding="utf-8").split()[0]

    reviews = completed["reviews"]
    assert completed["key_access_before_completion"] is False
    assert completed["review_count"] == len(reviews) == 32
    assert [item["blind_id"] for item in reviews] == [item["blind_id"] for item in packet["rows"]]
    assert len({item["blind_id"] for item in reviews}) == 32
    assert {item["review_choice"] for item in reviews} <= {"left", "right", "indistinguishable"}
    assert hashlib.sha256(COMPLETED_PATH.read_bytes()).hexdigest().upper() == sealed_hash


def test_stage1_verdict_recomputes_review_and_hard_gate_results() -> None:
    """摘要：解盲裁决必须由完成件、封存键与 candidate 硬 gate 机械复算。"""
    completed = runner._load_json(COMPLETED_PATH)
    key = runner._load_json(KEY_PATH)
    verdict = runner._load_json(STAGE1_VERDICT_PATH)
    review_by_id = {item["blind_id"]: item["review_choice"] for item in completed["reviews"]}

    target_results: dict[str, Counter[str]] = {}
    raw_wins = 0
    adjusted_successes = 0
    hard_gate_passes = 0
    for item in key["rows"]:
        choice = review_by_id[item["blind_id"]]
        raw_win = choice == item["candidate_side"]
        gate_passed = all(item["candidate_automatic_gate"].values())
        success = raw_win and gate_passed
        counts = target_results.setdefault(item["target"], Counter())
        counts["comparisons"] += 1
        counts[f"choice_{choice}"] += 1
        counts["raw_wins"] += raw_win
        counts["gate_passes"] += gate_passed
        counts["successes"] += success
        raw_wins += raw_win
        hard_gate_passes += gate_passed
        adjusted_successes += success

    assert Counter(item["review_choice"] for item in completed["reviews"]) == Counter(
        verdict["review_counts"]
    )
    assert raw_wins == verdict["decision"]["raw_candidate_wins"] == 10
    assert hard_gate_passes == verdict["candidate_hard_gate"]["passed"] == 28
    assert adjusted_successes == verdict["decision"]["hard_gate_adjusted_successes"] == 9
    assert verdict["decision"]["passed"] is False
    for target, expected in verdict["target_results"].items():
        actual = target_results[target]
        assert actual["comparisons"] == expected["comparisons"]
        assert actual["raw_wins"] == expected["raw_candidate_wins"]
        assert actual["gate_passes"] == expected["candidate_hard_gate_passed"]
        assert actual["successes"] == expected["hard_gate_adjusted_successes"]


def test_no_effect_closure_preserves_claim_boundary_and_engineering_consequence() -> None:
    """摘要：失败分支必须停止确认集且不得冒充单格确认或新增采样协议。"""
    closure = yaml.safe_load(NO_EFFECT_SPEC_PATH.read_text(encoding="utf-8"))
    outcomes = closure["target_outcomes"]

    assert hashlib.sha256(COMPLETED_PATH.read_bytes()).hexdigest().upper() == closure["trace"][
        "confirmation_stage1_completed_review_sha256"
    ]
    assert hashlib.sha256(STAGE1_VERDICT_PATH.read_bytes()).hexdigest().upper() == closure["trace"][
        "confirmation_stage1_verdict_sha256"
    ]
    assert closure["scope"]["decision"] == "no_effect_observed_within_preregistered_grid"
    assert closure["evidence"]["confirmation_stage1"]["hard_gate_adjusted_successes"] == 9
    assert closure["evidence"]["confirmation_stage1"]["remaining_confirmation_pairs_cancelled"] == 128
    assert len(outcomes) == 10
    assert {item["decoder_delta"] for item in outcomes.values()} == {0.0}
    assert sum(item["state"] == "confirmation_stage1_gate_failed" for item in outcomes.values()) == 4
    assert all(item["state"] != "confirmed_no_effect" for item in outcomes.values())
    assert closure["engineering_contract"]["add_persona_sampling_dto"] is False
    assert closure["engineering_contract"]["change_generation_options_schema_for_persona"] is False
    assert closure["engineering_contract"]["apply_persona_decoder_deltas"] is False
    assert closure["claim_boundary"]["claim_all_sampling_parameters_are_ineffective"] is False
