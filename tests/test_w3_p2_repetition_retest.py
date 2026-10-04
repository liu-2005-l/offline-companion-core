"""摘要：W3-P2-2 复测 runner 与盲评包构建器的机械口径测试。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_w3_p2_blind_review import build_blind_review
from scripts.run_w3_p2_repetition_retest import (
    _acceptance,
    _arm_config,
    _trace_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _decision(
    action: str,
    *,
    score: float | None = None,
    reason: str = "threshold_not_matched",
) -> dict[str, object]:
    return {
        "action": action,
        "score": score,
        "threshold": 0.09,
        "comparison": "gt",
        "previous_ngrams": 10,
        "current_ngrams": 10,
        "reason": reason,
        "confirmation_intent": False,
    }


def _case(
    case_id: str,
    *,
    replies: list[str],
    traces: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "id": case_id,
        "scenario": "chat",
        "group": case_id,
        "turns": [{"user": f"turn-{index}"} for index in range(len(replies))],
        "replies": replies,
        "repetition_traces": traces,
        "l4_traces": [{"outcome": "bypass"} for _reply in replies],
    }


def _run(metric: float, case: dict[str, object]) -> dict[str, object]:
    return {
        "cases": [case],
        "metrics": {"aggregate": {"cross_turn_4gram_jaccard_mean": metric}},
        "validation_cases": [],
        "validation_metrics": {"aggregate": {"cross_turn_4gram_jaccard_mean": 0.0}},
    }


def test_retest_configs_enable_guard_for_both_style_arms() -> None:
    """摘要：A/B 均开启 style 与 guard，仅 B 开启身份近端提醒。"""

    arm_a = _arm_config("A")
    arm_b = _arm_config("B")

    assert arm_a.style_examples_enabled is True
    assert arm_a.identity_near_prompt_enabled is False
    assert arm_a.cross_turn_repetition_guard_enabled is True
    assert arm_b.style_examples_enabled is True
    assert arm_b.identity_near_prompt_enabled is True
    assert arm_b.cross_turn_repetition_guard_enabled is True


def test_trigger_rows_select_first_retry_and_require_retry_direct_below_gate() -> None:
    """摘要：触发样本只按 first retry 筛选，L4-only 复检不得混入。"""

    triggered_trace = {
        "first": _decision("retry", score=0.2, reason="threshold_matched"),
        "retry": _decision("direct", score=0.01),
        "retry_taken": True,
        "outcome": "retry",
    }
    l4_only_trace = {
        "first": _decision("direct", score=0.01),
        "retry": _decision("direct", score=0.01),
        "retry_taken": False,
        "outcome": "retry",
    }
    payload = {
        "arms": {
            "A": {
                "case_runs": {
                    "seed42": _run(
                        0.01,
                        _case(
                            "S16-S18",
                            replies=["alpha repeated phrase", "beta fresh answer"],
                            traces=[triggered_trace, l4_only_trace],
                        ),
                    )
                }
            }
        }
    }

    triggered, gaps = _trace_rows(payload)

    assert len(triggered) == 1
    assert triggered[0]["turn_index"] == 0
    assert triggered[0]["retry_action"] == "direct"
    assert triggered[0]["retry_below_0_02"] is True
    assert gaps == []


def test_acceptance_keeps_original_arm_gate_and_fails_any_red_arm() -> None:
    """摘要：A/B 各自三 seed 聚合，任一 arm 超过原线即整体失败。"""

    direct_trace = {
        "first": _decision("direct", score=0.0),
        "retry": None,
        "retry_taken": False,
        "outcome": "direct",
    }
    case = _case("S01", replies=["safe"], traces=[direct_trace])
    payload = {
        "arms": {
            "A": {
                "case_runs": {
                    "seed42": _run(0.01, case),
                    "seed1337": _run(0.02, case),
                    "seed2024": _run(0.03, case),
                }
            },
            "B": {
                "case_runs": {
                    "seed42": _run(0.04, case),
                    "seed1337": _run(0.04, case),
                    "seed2024": _run(0.04, case),
                }
            },
        }
    }

    result = _acceptance(payload)

    assert result["arm_gates"]["A"]["aggregate_mean"] == 0.02
    assert result["arm_gates"]["A"]["passed"] is True
    assert result["arm_gates"]["B"]["passed"] is False
    assert result["global_gate_passed"] is False
    assert result["mechanical_status"] == "failed"


def test_blind_builder_pairs_pre_and_post_for_both_arms_without_labels() -> None:
    """摘要：盲包覆盖双臂同 case，映射仅存在独立 key。"""

    def matrix(reply_suffix: str) -> dict[str, object]:
        arms = {}
        for arm in ("A", "B"):
            arms[arm] = {
                "case_runs": {
                    "seed42": {
                        "cases": [
                            {
                                "id": "S01",
                                "scenario": "chat",
                                "turns": [{"user": "hello"}],
                                "replies": [f"{arm}-{reply_suffix}"],
                            }
                        ]
                    }
                }
            }
        return {"arms": arms}

    pre = matrix("pre")
    post = matrix("post")
    review, key = build_blind_review(
        {"A": pre, "B": pre},
        post,
        seed_name="seed42",
        shuffle_seed=20261004,
    )

    assert len(review["cases"]) == 2
    assert all(row["preferred"] is None for row in review["cases"])
    assert all("repaired" not in json.dumps(row) for row in review["cases"])
    assert {row["blind_id"] for row in key["mapping"]} == {"A-S01", "B-S01"}


def test_validation_fixture_has_three_separate_two_turn_observation_cases() -> None:
    """摘要：新增同构验证对独立于原始 gate，且固定为三个两轮短追问。"""

    path = (
        REPO_ROOT
        / "fixtures"
        / "persona_expression"
        / "w3_p2_2_validation_cases.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["version"] == "w3-p2-2-validation-v1"
    assert len(payload["cases"]) == 3
    assert all(len(case["turns"]) == 2 for case in payload["cases"])
    assert all(case["scenario"] == "memory" for case in payload["cases"])
