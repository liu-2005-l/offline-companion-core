from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest
from scripts.build_w3_closure_r0_guard_blind_review import (
    BlindSamplingError,
    _validate_audit,
    build_sampling_materials,
)


def _case(case_id: str, replies: list[str], *, trace_reason: str) -> dict:
    turns = [{"user": f"{case_id}-user-{index}"} for index in range(len(replies))]
    traces = [
        {
            "outcome": "bypass" if index == 0 else "direct",
            "first": {
                "reason": trace_reason if index == 0 else "threshold_not_matched"
            },
            "retry_taken": False,
        }
        for index in range(len(replies))
    ]
    return {
        "id": case_id,
        "turns": turns,
        "replies": replies,
        "repetition_traces": traces,
    }


def _matrix(*, repaired: bool) -> dict:
    runs = {}
    for seed in (42, 1337):
        multi_replies = ["same-first", "repaired"] if repaired else ["same-first", "pre-fix"]
        if seed != 42:
            multi_replies = ["same-first", "same-second"]
        cases = [
            _case("S01", ["same-s01"], trace_reason="missing_previous_or_current_reply"),
            _case("T01", ["same-t01"], trace_reason="missing_previous_or_current_reply"),
            _case("M01", ["same-m01"], trace_reason="missing_previous_or_current_reply"),
            _case("M09-M10", multi_replies, trace_reason="missing_previous_or_current_reply"),
        ]
        if repaired and seed == 42:
            repair_trace = cases[-1]["repetition_traces"][1]
            repair_trace["outcome"] = "retry"
            repair_trace["first"]["reason"] = "threshold_matched"
            repair_trace["retry_taken"] = True
        runs[f"seed{seed}"] = {"cases": cases}
    return {"arms": {"B": {"case_runs": runs}}}


def _protocol() -> dict:
    return {
        "frozen_sources": {
            "w2_matrix": {"arm": "B"},
            "p2_matrix": {"arm": "B"},
        },
        "sample_construction": {
            "multi_turn_repair": {
                "current_expected_keys": [
                    {"seed": 42, "scenario_id": "M09-M10", "turn_index": 1}
                ]
            },
            "single_turn_no_spill": {
                "current_scenario_ids": ["S01", "T01", "M01"],
                "current_candidate_turn_count": 6,
            },
            "current_expected_n": 4,
        },
    }


def test_sampling_hides_stratum_and_balances_each_reviewer() -> None:
    packets, key, summary = build_sampling_materials(
        _protocol(),
        _matrix(repaired=False),
        _matrix(repaired=True),
        protocol_anchor_commit="a" * 40,
    )

    assert summary["pair_count"] == 4
    assert summary["stratum_counts"] == {
        "multi_turn_repair": 1,
        "single_turn_no_spill": 3,
    }
    for reviewer_id, packet in packets.items():
        assert len(packet["pairs"]) == 4
        assert all(
            set(row) == {"pair_id", "context", "reply_A", "reply_B"}
            for row in packet["pairs"]
        )
        mapping = key["reviewers"][reviewer_id]
        assert sum(row["reply_A_source"] == "repaired" for row in mapping) == 2
        assert {row["stratum"] for row in mapping} == {
            "multi_turn_repair",
            "single_turn_no_spill",
        }


def test_sampling_is_deterministic_for_same_anchor() -> None:
    first = build_sampling_materials(
        _protocol(),
        _matrix(repaired=False),
        _matrix(repaired=True),
        protocol_anchor_commit="b" * 40,
    )
    second = build_sampling_materials(
        _protocol(),
        _matrix(repaired=False),
        _matrix(repaired=True),
        protocol_anchor_commit="b" * 40,
    )

    assert first == second


def test_sampling_rejects_single_turn_difference() -> None:
    p2_matrix = _matrix(repaired=True)
    p2_matrix["arms"]["B"]["case_runs"]["seed42"]["cases"][0]["replies"][0] = (
        "unexpected"
    )

    with pytest.raises(BlindSamplingError, match="单轮文本非逐字节一致"):
        build_sampling_materials(
            _protocol(),
            _matrix(repaired=False),
            p2_matrix,
            protocol_anchor_commit="c" * 40,
        )


def test_sampling_rejects_single_turn_guard_trace() -> None:
    p2_matrix = deepcopy(_matrix(repaired=True))
    trace = p2_matrix["arms"]["B"]["case_runs"]["seed42"]["cases"][0][
        "repetition_traces"
    ][0]
    trace["outcome"] = "direct"

    with pytest.raises(BlindSamplingError, match="单轮旁路形态异常"):
        build_sampling_materials(
            _protocol(),
            _matrix(repaired=False),
            p2_matrix,
            protocol_anchor_commit="d" * 40,
        )


def test_audit_accepts_only_exact_or_git_normalized_line_endings() -> None:
    matrix_bytes = b'{\n  "value": 1\n}\n'
    generation_bytes = matrix_bytes.replace(b"\n", b"\r\n")
    audit = {
        "audit_schema": 1,
        "meta": {
            "provenance_complete": True,
            "matrix_sha256": hashlib.sha256(generation_bytes).hexdigest(),
        },
        "checkpoints": [{"provenance": {"git_commit": "f" * 40}}],
    }

    result = _validate_audit(
        audit,
        matrix_bytes,
        generation_commit="f" * 40,
        label="fixture",
    )

    assert result["hash_match_mode"] == "git_lf_to_generation_crlf"


def test_audit_rejects_unknown_matrix_hash_difference() -> None:
    audit = {
        "audit_schema": 1,
        "meta": {"provenance_complete": True, "matrix_sha256": "0" * 64},
        "checkpoints": [{"provenance": {"git_commit": "f" * 40}}],
    }

    with pytest.raises(BlindSamplingError, match="matrix_sha256 不匹配"):
        _validate_audit(
            audit,
            b"{}\n",
            generation_commit="f" * 40,
            label="fixture",
        )
