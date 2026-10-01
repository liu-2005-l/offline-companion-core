"""摘要：W3-P2-1a 纯复读检测器、判别 fixture 与阈值扫描器测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from offline_companion.core.persona_session.expression import PersonaExpressionConfig
from offline_companion.core.persona_session.repetition_guard import (
    CONFIRMATION_INTENT_MAX_CHARS,
    CrossTurnRepetitionTrace,
    cross_turn_repetition_score,
    decide_cross_turn_repetition,
    detect_confirmation_intent,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "persona_expression" / "w3_p2_repetition_pairs.json"
SCRIPT = ROOT / "scripts" / "calibrate_w3_p2_repetition_threshold.py"
CALIBRATION = (
    ROOT / "artifacts" / "persona_expression" / "w3_p2_repetition_calibration_v0_2.json"
)
SESSION_SOURCE = ROOT / "src" / "offline_companion" / "core" / "persona_session" / "session.py"

EXPECTED_POSITIVE_IDS = {
    "archive_b_seed42_m09_m10",
    "archive_b_seed1337_m09_m10",
    "archive_a_seed1337_s16_s17",
    "archive_a_seed1337_m09_m10",
}
EXPECTED_BASELINE_IDS = {
    "baseline_seed42_s16_s17",
    "baseline_seed42_s17_s18",
    "baseline_seed42_m09_m10",
    "baseline_seed1337_s16_s17",
    "baseline_seed1337_s17_s18",
    "baseline_seed1337_m09_m10",
    "baseline_seed2024_s16_s17",
    "baseline_seed2024_s17_s18",
    "baseline_seed2024_m09_m10",
}


def _fixture() -> dict[str, object]:
    """摘要：读取 P2-1a 判别 fixture。"""

    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _stdout_fields(stdout: str) -> dict[str, str]:
    """摘要：把扫描器稳定的 key=value 输出转为字典。"""

    return {
        key: value
        for line in stdout.splitlines()
        if "=" in line
        for key, value in [line.split("=", maxsplit=1)]
    }


def test_w3_p2_fixture_has_required_arms_controls_and_categories() -> None:
    """摘要：判别对精确覆盖冻结正例、baseline 全多轮转移与三类负控。"""

    data = _fixture()
    positive = data["positive"]
    negative = data["negative"]

    assert data["version"] == "0.2"
    assert data["ngram_size"] == 4
    assert len([*positive, *negative]) == 25
    assert {pair["id"] for pair in positive} == EXPECTED_POSITIVE_IDS
    assert {pair["id"] for pair in negative if pair["category"] == "baseline_archive"} == (
        EXPECTED_BASELINE_IDS
    )
    assert {pair["arm"] for pair in positive} == {"A", "B"}
    assert {pair["category"] for pair in negative} >= {
        "baseline_archive",
        "healthy_continuation",
        "explicit_quote",
        "explicit_confirmation",
        "short_reply",
    }
    assert all(isinstance(pair["user_message"], str) for pair in [*positive, *negative])
    assert all(
        isinstance(pair["expects_user_confirmation"], bool)
        for pair in [*positive, *negative]
    )


def test_w3_p2_archived_score_anchors_match_exact_pairs() -> None:
    """摘要：归档锚逐对复算，禁止用 group 均值或任一路径命中蹭过。"""

    data = _fixture()
    anchored = {
        pair["id"]: pair
        for pair in [*data["positive"], *data["negative"]]
        if "expected_score" in pair
    }

    assert len(anchored) == 20
    actual = {
        pair_id: cross_turn_repetition_score(pair["previous_reply"], pair["current_reply"])
        for pair_id, pair in anchored.items()
    }
    expected = {pair_id: pair["expected_score"] for pair_id, pair in anchored.items()}
    assert actual == pytest.approx(expected, abs=0.0000005)
    assert actual["archive_b_seed42_m09_m10"] == pytest.approx(0.243902, abs=0.0000005)
    assert actual["baseline_seed42_s16_s17"] == pytest.approx(0.089744, abs=0.0000005)


def test_w3_p2_archived_user_messages_match_source_turns() -> None:
    """摘要：20 个归档对的用户输入必须逐对回源到矩阵原始轮次。"""

    pairs = [
        pair
        for pair in [*_fixture()["positive"], *_fixture()["negative"]]
        if "source" in pair
    ]

    assert len(pairs) == 20
    for pair in pairs:
        source = json.loads((ROOT / pair["source"]).read_text(encoding="utf-8"))
        runs = (
            source["arms"][pair["arm"]]["case_runs"]
            if "arms" in source
            else source["case_runs"]
        )
        matches = []
        for seed_run in runs.values():
            for case in seed_run["cases"]:
                for index in range(1, len(case["replies"])):
                    if (
                        case["replies"][index - 1] == pair["previous_reply"]
                        and case["replies"][index] == pair["current_reply"]
                    ):
                        matches.append(case["turns"][index]["user"])
        assert matches == [pair["user_message"]], pair["id"]


def test_w3_p2_detector_bypasses_missing_context_and_freezes_comparison_boundary() -> None:
    """摘要：无上一轮时旁路，gt/gte 在等值格产生不同且精确的动作。"""

    bypass = decide_cross_turn_repetition(
        "",
        "当前回复",
        threshold=0.5,
        comparison="gt",
    )
    strict = decide_cross_turn_repetition(
        "完全相同的回复",
        "完全相同的回复",
        threshold=1.0,
        comparison="gt",
    )
    inclusive = decide_cross_turn_repetition(
        "完全相同的回复",
        "完全相同的回复",
        threshold=1.0,
        comparison="gte",
    )

    assert bypass.action == "bypass"
    assert bypass.score is None
    assert strict.action == "direct"
    assert strict.score == 1.0
    assert inclusive.action == "retry"
    assert inclusive.score == 1.0


def test_w3_p2_trace_is_independent_and_defaults_to_bypass() -> None:
    """摘要：复读 trace 自成 DTO，默认态不借用 PersonaL4Trace 语义。"""

    trace = CrossTurnRepetitionTrace()

    assert trace.enabled is False
    assert trace.first is None
    assert trace.retry is None
    assert trace.retry_taken is False
    assert trace.outcome == "bypass"


def test_w3_p2_scanner_reports_both_calibration_modes_without_hiding_paths(
    tmp_path,
) -> None:
    """摘要：strict 保留无召回结论，意图口径冻结零误拦三正例路径。"""

    output = tmp_path / "calibration.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json-output", str(output)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    fields = _stdout_fields(result.stdout)
    assert fields["strict.positive_count"] == "4"
    assert fields["strict.negative_count"] == "21"
    assert fields["strict.anchor_count"] == "20"
    assert fields["strict.decision"] == "zero_fp_no_recall"
    assert fields["strict.recommended_comparison"] == "gt"
    assert fields["strict.true_positive_ids"] == ""
    assert fields["strict.false_positive_ids"] == ""
    assert set(fields["strict.false_negative_ids"].split(",")) == EXPECTED_POSITIVE_IDS
    assert fields["strict.max_negative_ids"] == "explicit_confirmation_project_order"
    assert float(fields["strict.max_negative_score"]) > float(
        fields["strict.max_positive_score"]
    )
    assert int(fields["strict.evaluated_candidate_count"]) > 2

    assert fields["intent_aware.decision"] == "zero_fp_candidate"
    assert fields["intent_aware.recommended_threshold"] == "0.089744"
    assert fields["intent_aware.recommended_comparison"] == "gt"
    assert fields["intent_aware.false_positive_ids"] == ""
    assert set(fields["intent_aware.true_positive_ids"].split(",")) == {
        "archive_b_seed42_m09_m10",
        "archive_a_seed1337_s16_s17",
        "archive_a_seed1337_m09_m10",
    }
    assert fields["intent_aware.false_negative_ids"] == "archive_b_seed1337_m09_m10"
    assert set(fields["intent_aware.exempt_negative_ids"].split(",")) == {
        "explicit_quote_hiking_plan",
        "explicit_confirmation_project_order",
    }

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["strict"]["decision"] == "zero_fp_no_recall"
    assert payload["strict"]["false_positive_ids"] == []
    assert set(payload["strict"]["false_negative_ids"]) == EXPECTED_POSITIVE_IDS
    assert payload["intent_aware"]["decision"] == "zero_fp_candidate"
    assert payload["intent_aware"]["false_positive_ids"] == []
    assert payload == json.loads(CALIBRATION.read_text(encoding="utf-8"))


def test_w3_p2_scanner_anchor_tamper_fails_closed(tmp_path) -> None:
    """摘要：篡改归档预期得分时扫描器必须失败，不能静默重算后继续推荐。"""

    data = _fixture()
    data["positive"][0]["expected_score"] = 0.1
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(tampered)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode != 0
    assert "fixture_anchor_mismatch:archive_b_seed42_m09_m10" in result.stderr


@pytest.mark.parametrize(
    "user_message",
    [
        "好的，就按这个顺序来。",
        "嗯嗯",
        "你是说先修打包，再补文档？",
        "再说一遍刚才的",
        "你还记得我周六怎么安排的吗？",
    ],
)
def test_confirmation_intent_positive_variants(user_message: str) -> None:
    """摘要：确认、重申与引用请求的高置信变体必须命中。"""

    assert detect_confirmation_intent(user_message) is True


@pytest.mark.parametrize(
    "user_message",
    [
        "不用了，先别按这个来",
        "可以吗？还能再改吗",
        "等等，再想想",
        "对了，今晚再加个测试",
        "不对，你是说先修打包吗？",
        "嗯",
        "",
        None,
        "确" * (CONFIRMATION_INTENT_MAX_CHARS + 1),
    ],
)
def test_confirmation_intent_negative_controls(user_message: str | None) -> None:
    """摘要：否定、疑问、反悔、追加、模糊与超长输入不得获得豁免。"""

    assert detect_confirmation_intent(user_message) is False


def test_intent_exempt_uses_production_decision_path() -> None:
    """摘要：合法确认负例由生产判定路径旁路，且不计算重合分数。"""

    pair = next(
        pair
        for pair in _fixture()["negative"]
        if pair["id"] == "explicit_confirmation_project_order"
    )
    decision = decide_cross_turn_repetition(
        pair["previous_reply"],
        pair["current_reply"],
        threshold=0.089744,
        comparison="gt",
        user_message=pair["user_message"],
    )

    assert decision.action == "bypass"
    assert decision.reason == "user_confirmation_exempt"
    assert decision.score is None
    assert decision.threshold is None
    assert decision.confirmation_intent is True


def test_fixture_intent_labels_match_detector_for_every_pair() -> None:
    """摘要：全部 fixture 期望标签必须与生产意图判定机械一致。"""

    pairs = [*_fixture()["positive"], *_fixture()["negative"]]

    assert len(pairs) == 25
    assert {
        pair["id"]
        for pair in pairs
        if detect_confirmation_intent(pair["user_message"])
    } == {
        pair["id"] for pair in pairs if pair["expects_user_confirmation"]
    }


def test_fixture_intent_label_tamper_fails_closed(tmp_path) -> None:
    """摘要：篡改语义标签时扫描器必须在加载期失败。"""

    data = _fixture()
    data["negative"][-1]["expects_user_confirmation"] = True
    tampered = tmp_path / "tampered-intent.json"
    tampered.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(tampered)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode != 0
    assert "fixture_intent_label_mismatch:short_reply_transition" in result.stderr


def test_intent_aware_counts_every_negative_in_confusion_partition(tmp_path) -> None:
    """摘要：普通 TN、豁免 TN 与 FP 必须精确分割全部负例。"""

    output = tmp_path / "calibration.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json-output", str(output)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    intent_aware = json.loads(output.read_text(encoding="utf-8"))["intent_aware"]
    assert (
        intent_aware["true_negative_count"]
        + len(intent_aware["exempt_negative_ids"])
        + len(intent_aware["false_positive_ids"])
        == intent_aware["negative_count"]
        == 21
    )


def test_restatement_question_beats_question_veto_but_not_negation() -> None:
    """摘要：重申请求仅跳过疑问 veto，不得跳过否定 veto。"""

    assert detect_confirmation_intent("你是说先修打包，再补文档？") is True
    assert detect_confirmation_intent("不对，你是说先修打包吗？") is False


def test_w3_p2_1a_has_no_runtime_wiring() -> None:
    """摘要：P2-1a 只交付纯模块，session 与 A/B 配置面保持零接线。"""

    session_source = SESSION_SOURCE.read_text(encoding="utf-8")
    assert "repetition_guard" not in session_source
    assert "cross_turn_repetition_guard" not in session_source
    assert set(PersonaExpressionConfig.__dataclass_fields__) == {
        "style_examples_enabled",
        "identity_near_prompt_enabled",
    }
