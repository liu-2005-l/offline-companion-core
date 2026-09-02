"""生成拟人表述 W2 的 TA 盲评包与独立映射表。"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "artifacts" / "persona_expression" / "w1_b1_controlled_rerun.json"
DEFAULT_CANDIDATE = REPO_ROOT / "artifacts" / "persona_expression" / "w2_arm_b_matrix.json"
DEFAULT_REVIEW = REPO_ROOT / "artifacts" / "persona_expression" / "w2_blind_review.json"
DEFAULT_KEY = REPO_ROOT / "artifacts" / "persona_expression" / "w2_blind_review_key.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_blind_review(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    seed_name: str,
    shuffle_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """摘要：按同 seed 配对 baseline 与候选臂，生成 S+M 子集盲评材料。"""
    baseline_cases = {
        item["id"]: item
        for item in baseline["case_runs"][seed_name]["cases"]
        if item["scenario"] in {"chat", "memory"}
    }
    arm_name = next(iter(candidate["arms"]))
    candidate_cases = {
        item["id"]: item
        for item in candidate["arms"][arm_name]["case_runs"][seed_name]["cases"]
        if item["scenario"] in {"chat", "memory"}
    }
    if baseline_cases.keys() != candidate_cases.keys():
        raise RuntimeError("baseline 与候选臂的 S+M 判例集合不一致")

    rng = random.Random(shuffle_seed)
    review_rows = []
    key_rows = []
    for case_id, baseline_case in baseline_cases.items():
        candidate_case = candidate_cases[case_id]
        candidate_first = bool(rng.getrandbits(1))
        option_a = candidate_case["replies"] if candidate_first else baseline_case["replies"]
        option_b = baseline_case["replies"] if candidate_first else candidate_case["replies"]
        review_rows.append(
            {
                "case_id": case_id,
                "scenario": baseline_case["scenario"],
                "turns": baseline_case["turns"],
                "option_a": option_a,
                "option_b": option_b,
                "preferred": None,
                "reason": "",
            }
        )
        key_rows.append(
            {
                "case_id": case_id,
                "option_a": arm_name if candidate_first else "baseline",
                "option_b": "baseline" if candidate_first else arm_name,
            }
        )
    review = {
        "meta": {
            "version": "w2-blind-v1",
            "seed_name": seed_name,
            "scenarios": ["chat", "memory"],
            "instructions": "逐条在 preferred 填 A/B/平手，并在 reason 写一句理由；不要打开映射表。",
        },
        "cases": review_rows,
    }
    key = {
        "meta": {
            "version": "w2-blind-key-v1",
            "seed_name": seed_name,
            "shuffle_seed": shuffle_seed,
            "candidate_arm": arm_name,
        },
        "mapping": key_rows,
    }
    return review, key


def main() -> int:
    """摘要：命令行入口，写出盲评包与映射表。"""
    parser = argparse.ArgumentParser(description="生成拟人表述 W2 TA 盲评包")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--seed-name", default="seed42")
    parser.add_argument("--shuffle-seed", type=int, default=20260831)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--key-output", type=Path, default=DEFAULT_KEY)
    args = parser.parse_args()
    review, key = build_blind_review(
        _read_json(args.baseline),
        _read_json(args.candidate),
        seed_name=args.seed_name,
        shuffle_seed=args.shuffle_seed,
    )
    _write_json(args.review_output, review)
    _write_json(args.key_output, key)
    print(args.review_output)
    print(args.key_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
