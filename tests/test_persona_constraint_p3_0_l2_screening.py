from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

runner = importlib.import_module("run_persona_constraint_p3_0_l2_screening")
SPEC_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p3_0_l2_screening_spec.yaml"
REVIEW_PROTOCOL_PATH = (
    REPO_ROOT / "fixtures" / "persona_constraints" / "p3_0_l2_screening_review_protocol.yaml"
)
SPEC = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
REVIEW_PROTOCOL = yaml.safe_load(REVIEW_PROTOCOL_PATH.read_text(encoding="utf-8"))
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "persona_constraints" / "p3_0_l2_screening"
BLIND_PACKET_PATH = ARTIFACT_ROOT / "blind_review_packet.json"
BLIND_KEY_PATH = ARTIFACT_ROOT / "blind_review_key.json"
COMPLETED_REVIEW_PATH = ARTIFACT_ROOT / "blind_review_completed.json"
BLIND_VERDICT_PATH = ARTIFACT_ROOT / "blind_review_verdict.json"
BALANCED_PACKET_PATH = ARTIFACT_ROOT / "blind_review_packet_balanced_v2.json"
BALANCED_KEY_PATH = ARTIFACT_ROOT / "blind_review_key_balanced_v2.json"
BALANCED_COMPLETED_PATH = ARTIFACT_ROOT / "blind_review_completed_balanced_v2.json"
BALANCED_VERDICT_PATH = ARTIFACT_ROOT / "blind_review_verdict_balanced_v2.json"
SOURCES = runner.load_sources(SPEC)


def test_screening_source_hashes_and_static_preflight_are_green() -> None:
    """摘要：筛选只接受冻结哈希一致且检测器正控有效的输入资产。"""
    result = runner.static_preflight(SPEC, SOURCES)

    assert result["passed"] is True
    assert all(item["passed"] for item in result["source_hashes"])
    assert result["l4"]["true_positives"] == 50
    assert result["l4"]["false_positives"] == 0
    assert result["copy_probe"]["hit"] is True


def test_screening_matrix_is_exactly_320_rows_with_four_outputs_per_arm() -> None:
    """摘要：十目标格、八 arm 与四输出的矩阵必须机械展开为 320 轮。"""
    rows = runner.matrix_rows(SPEC, SOURCES["dimension_corpus"])

    assert len(rows) == SPEC["matrix"]["total_output_count"] == 320
    assert len({row["row_id"] for row in rows}) == 320
    counts = Counter((row["dimension"], row["level"], row["arm_id"]) for row in rows)
    assert set(counts.values()) == {4}
    assert len(counts) == 5 * 2 * 8


def test_low_and_high_share_preregistered_held_out_prompts() -> None:
    """摘要：同维 low/high 共用预注册 prompt，且与注入问句无近重复。"""
    prompts = runner.selected_prompts(SPEC, SOURCES["dimension_corpus"])
    rows = runner.matrix_rows(SPEC, SOURCES["dimension_corpus"])
    leakage = runner.prompt_leakage_checks(SPEC, SOURCES["dimension_corpus"])

    assert set(prompts) == {"O", "C", "E", "A", "N"}
    for dimension, selected in prompts.items():
        assert len(selected) == 2
        low = {row["user"] for row in rows if row["dimension"] == dimension and row["level"] == "low"}
        high = {row["user"] for row in rows if row["dimension"] == dimension and row["level"] == "high"}
        assert low == high == {item["text"] for item in selected}
        assert all(item["source_unit"] == "held_out_preregistered" for item in selected)
    assert len(leakage) == 10
    assert all(item["passed"] for item in leakage)


def test_candidate_arms_change_only_one_axis_and_keep_repeat_penalty_neutral() -> None:
    """摘要：候选仅改变 temperature 或 top_p，复制混杂参数固定为中性。"""
    baseline = SPEC["generation"]["baseline"]

    for arm in SPEC["generation"]["candidate_arms"]:
        decode = runner.decode_for_arm(SPEC, arm)
        changed = {key for key in decode if decode[key] != baseline[key]}
        expected = set() if arm["id"] == "baseline" else {arm["parameter"]}
        assert changed == expected
        assert decode["repeat_penalty"] == 1.0


def test_messages_use_system_embedded_target_without_history_injection() -> None:
    """摘要：screening 沿用 F0b 单维 system 内嵌载体，不把示例放进历史。"""
    row = runner.matrix_rows(SPEC, SOURCES["dimension_corpus"])[0]
    messages, examples = runner.build_messages(SPEC, SOURCES["dimension_corpus"], row)

    assert [message["role"] for message in messages] == ["system", "user"]
    assert f"{row['dimension']} / {row['level']}" in messages[0]["content"]
    assert len(examples) == 4
    assert all(example in messages[0]["content"] for example in examples)


def test_blind_packet_hides_arm_and_has_280_stable_pairs() -> None:
    """摘要：盲审包隐藏候选参数身份，解盲键单独保存。"""
    matrix = runner.matrix_rows(SPEC, SOURCES["dimension_corpus"])
    fake_rows = []
    for row in matrix:
        fake_rows.append(
            {
                **row,
                "reply": f"reply-{row['row_id']}",
                "automatic_passed": True,
            }
        )

    packet, key = runner.build_blind_review(SPEC, SOURCES["dimension_corpus"], fake_rows)
    eligible = runner.filter_eligible_review(packet, key, fake_rows)

    assert len(packet["rows"]) == len(key["rows"]) == 280
    assert len(eligible["rows"]) == 280
    assert all("arm_id" not in item and "candidate_side" not in item for item in packet["rows"])
    assert {item["candidate_side"] for item in key["rows"]} == {"left", "right"}

    placements = Counter(
        (
            item["candidate_row_id"].split("-", 2)[0],
            item["candidate_row_id"].split("-", 2)[1],
            item["arm_id"],
            item["candidate_side"],
        )
        for item in key["rows"]
    )
    arm_keys = {(dimension, level, arm_id) for dimension, level, arm_id, _ in placements}
    assert all(placements[(*arm_key, "left")] == 2 for arm_key in arm_keys)
    assert all(placements[(*arm_key, "right")] == 2 for arm_key in arm_keys)


def test_review_protocol_freezes_ties_selection_and_unused_budget() -> None:
    """摘要：盲审选项、三过四门线与七格省余预算必须在开 key 前固定。"""
    assert REVIEW_PROTOCOL["choice_contract"]["enum"] == ["left", "right", "indistinguishable"]
    assert REVIEW_PROTOCOL["pair_scoring"]["indistinguishable"] == "failure"
    assert REVIEW_PROTOCOL["pair_scoring"]["denominator"] == "fixed_four_pairs"
    assert REVIEW_PROTOCOL["arm_gate"]["minimum_successes"] == 3
    assert REVIEW_PROTOCOL["arm_gate"]["comparisons"] == 4
    assert REVIEW_PROTOCOL["already_excluded_targets"] == ["O_low", "O_high", "E_high"]
    budget = REVIEW_PROTOCOL["confirmation_budget"]
    assert budget["pair_items"] == 7 * 40 == 280
    assert budget["maximum_output_generations"] == 440
    assert budget["saved_budget_action"] == "abandon_not_reallocate"


def test_completed_blind_review_is_sealed_before_key_and_recomputes_verdict() -> None:
    """摘要：完成件必须覆盖全部盲审项，且解盲成绩与固定候选可机械复算。"""
    packet = json.loads(BLIND_PACKET_PATH.read_text(encoding="utf-8"))
    key = json.loads(BLIND_KEY_PATH.read_text(encoding="utf-8"))
    completed = json.loads(COMPLETED_REVIEW_PATH.read_text(encoding="utf-8"))
    verdict = json.loads(BLIND_VERDICT_PATH.read_text(encoding="utf-8"))

    completed_hash = hashlib.sha256(COMPLETED_REVIEW_PATH.read_bytes()).hexdigest().upper()
    assert completed_hash == verdict["completed_review_sha256"]
    assert completed["status"] == "completed_before_key_access"
    assert completed["key_access_before_completion"] is False
    assert completed["review_count"] == len(completed["reviews"]) == 120
    assert [item["blind_id"] for item in completed["reviews"]] == [
        item["blind_id"] for item in packet["rows"]
    ]
    assert {item["review_choice"] for item in completed["reviews"]} <= set(
        REVIEW_PROTOCOL["choice_contract"]["enum"]
    )

    packet_by_id = {item["blind_id"]: item for item in packet["rows"]}
    key_by_id = {item["blind_id"]: item for item in key["rows"]}
    grouped: dict[tuple[str, str], list[bool]] = {}
    for review in completed["reviews"]:
        blind_id = review["blind_id"]
        packet_row = packet_by_id[blind_id]
        key_row = key_by_id[blind_id]
        target = f"{packet_row['dimension']}_{packet_row['level']}"
        grouped.setdefault((target, key_row["arm_id"]), []).append(
            review["review_choice"] == key_row["candidate_side"]
        )

    recomputed = [
        {
            "target": target,
            "arm_id": arm_id,
            "successes": sum(successes),
            "comparisons": len(successes),
            "passed": sum(successes) >= REVIEW_PROTOCOL["arm_gate"]["minimum_successes"],
        }
        for (target, arm_id), successes in sorted(grouped.items())
    ]
    assert recomputed == verdict["arm_results"]

    arm_by_id = {item["id"]: item for item in SPEC["generation"]["candidate_arms"]}
    parameter_order = {"temperature": 0, "top_p": 1}
    selected = []
    for target in sorted({item["target"] for item in recomputed}):
        passed = [item for item in recomputed if item["target"] == target and item["passed"]]
        if not passed:
            continue
        winner = min(
            passed,
            key=lambda item: (
                abs(arm_by_id[item["arm_id"]]["delta"]),
                -item["successes"],
                parameter_order[arm_by_id[item["arm_id"]]["parameter"]],
                arm_by_id[item["arm_id"]]["delta"] > 0,
            ),
        )
        selected.append({key: winner[key] for key in ("target", "arm_id", "successes", "comparisons")})
    assert selected == verdict["selected_candidates"]


def test_balanced_replacement_review_has_two_sides_per_arm_and_same_winners() -> None:
    """摘要：替代盲审必须逐 arm 左右各半，且完成件可复算稳定候选。"""
    packet = json.loads(BALANCED_PACKET_PATH.read_text(encoding="utf-8"))
    key = json.loads(BALANCED_KEY_PATH.read_text(encoding="utf-8"))
    completed = json.loads(BALANCED_COMPLETED_PATH.read_text(encoding="utf-8"))
    verdict = json.loads(BALANCED_VERDICT_PATH.read_text(encoding="utf-8"))

    completed_hash = hashlib.sha256(BALANCED_COMPLETED_PATH.read_bytes()).hexdigest().upper()
    assert completed_hash == verdict["completed_review_sha256"]
    assert completed["key_access_before_completion"] is False
    assert completed["review_count"] == len(completed["reviews"]) == len(packet["rows"]) == 120
    assert [item["blind_id"] for item in completed["reviews"]] == [
        item["blind_id"] for item in packet["rows"]
    ]

    packet_by_id = {item["blind_id"]: item for item in packet["rows"]}
    key_by_id = {item["blind_id"]: item for item in key["rows"]}
    placements: Counter[tuple[str, str, str]] = Counter()
    scores: Counter[tuple[str, str]] = Counter()
    for review in completed["reviews"]:
        blind_id = review["blind_id"]
        packet_row = packet_by_id[blind_id]
        key_row = key_by_id[blind_id]
        target = f"{packet_row['dimension']}_{packet_row['level']}"
        placements[(target, key_row["arm_id"], key_row["candidate_side"])] += 1
        if review["review_choice"] == key_row["candidate_side"]:
            scores[(target, key_row["arm_id"])] += 1

    arm_keys = {(target, arm_id) for target, arm_id, _ in placements}
    assert all(placements[(*arm_key, "left")] == 2 for arm_key in arm_keys)
    assert all(placements[(*arm_key, "right")] == 2 for arm_key in arm_keys)
    assert sum(scores.values()) == 46
    assert verdict["selected_candidates"] == [
        {"target": "A_high", "arm_id": "temperature_p010", "successes": 3, "comparisons": 4},
        {"target": "A_low", "arm_id": "top_p_m010", "successes": 3, "comparisons": 4},
        {"target": "C_low", "arm_id": "temperature_p005", "successes": 3, "comparisons": 4},
        {"target": "N_low", "arm_id": "temperature_p010", "successes": 3, "comparisons": 4},
    ]
