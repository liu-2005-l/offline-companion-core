from __future__ import annotations

from scripts.aggregate_w3_closure_r0_guard_blind_review import aggregate_unblinded


def _review(reviewer: str, choice: str) -> dict:
    return {
        "meta": {"reviewer": reviewer},
        "results": [{"pair_id": "G001", "choice": choice, "reason": "reason"}],
    }


def _key_row(*, a_source: str, stratum: str = "multi_turn_repair") -> dict:
    return {
        "pair_id": "G001",
        "stratum": stratum,
        "seed": 42,
        "scenario_id": "M09-M10",
        "turn_index": 1,
        "reply_A_source": a_source,
        "reply_B_source": "pre_fix" if a_source == "repaired" else "repaired",
    }


def test_unblind_maps_independent_positions_to_same_repaired_vote() -> None:
    reviews = {
        "prompt_side": _review("prompt_side", "A"),
        "context_free_ai_1": _review("context_free_ai_1", "B"),
        "context_free_ai_2": _review("context_free_ai_2", "B"),
    }
    key = {
        "reviewers": {
            "prompt_side": [_key_row(a_source="repaired")],
            "context_free_ai_1": [_key_row(a_source="pre_fix")],
            "context_free_ai_2": [_key_row(a_source="pre_fix")],
        }
    }

    aggregate = aggregate_unblinded(reviews, key)

    assert aggregate["pairs"][0]["majority"] == "repaired"
    assert aggregate["pairs"][0]["conforms"] is True
    assert aggregate["summary"]["deviation_count"] == 0


def test_unblind_expects_tie_for_single_turn_control() -> None:
    reviews = {
        reviewer: _review(reviewer, "tie")
        for reviewer in ("prompt_side", "context_free_ai_1", "context_free_ai_2")
    }
    key = {
        "reviewers": {
            reviewer: [_key_row(a_source="repaired", stratum="single_turn_no_spill")]
            for reviewer in reviews
        }
    }

    aggregate = aggregate_unblinded(reviews, key)

    assert aggregate["pairs"][0]["majority"] == "tie"
    assert aggregate["pairs"][0]["conforms"] is True
    assert aggregate["summary"]["statistical_significance_claimed"] is False


def test_unblind_records_nonconforming_outcome_without_rewriting_expectation() -> None:
    reviews = {
        "prompt_side": _review("prompt_side", "A"),
        "context_free_ai_1": _review("context_free_ai_1", "A"),
        "context_free_ai_2": _review("context_free_ai_2", "tie"),
    }
    key = {
        "reviewers": {
            reviewer: [_key_row(a_source="pre_fix")]
            for reviewer in reviews
        }
    }

    aggregate = aggregate_unblinded(reviews, key)

    assert aggregate["pairs"][0]["majority"] == "pre_fix"
    assert aggregate["pairs"][0]["expected"] == "repaired"
    assert aggregate["deviation_ledger"] == [
        {
            "pair_id": "G001",
            "stratum": "multi_turn_repair",
            "majority": "pre_fix",
            "expected": "repaired",
            "status": "requires_attribution",
        }
    ]
