"""摘要：生成 W3-P2-2 修复前后 A/B 双臂盲评包、密钥与预注册协议。"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "persona_expression"
DEFAULT_PRE_A = ARTIFACT_ROOT / "w2_arm_a_matrix.json"
DEFAULT_PRE_B = ARTIFACT_ROOT / "w2_arm_b_matrix.json"
DEFAULT_POST = ARTIFACT_ROOT / "w3_p2_2_ab_matrix.json"
DEFAULT_PACKET = ARTIFACT_ROOT / "w3_p2_2_blind_review.json"
DEFAULT_KEY = ARTIFACT_ROOT / "w3_p2_2_blind_review_key.json"
DEFAULT_PROTOCOL = ARTIFACT_ROOT / "w3_p2_2_blind_review_protocol.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _arm_runs(matrix: dict[str, Any], arm: str, seed_name: str) -> list[dict[str, Any]]:
    return list(matrix["arms"][arm]["case_runs"][seed_name]["cases"])


def build_blind_review(
    pre_by_arm: dict[str, dict[str, Any]],
    post: dict[str, Any],
    *,
    seed_name: str,
    shuffle_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """摘要：按同 arm、同 seed、同 case 配对修复前后用户可见回复。"""

    rng = random.Random(shuffle_seed)
    review_rows: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for arm in ("A", "B"):
        pre_cases = {
            item["id"]: item
            for item in _arm_runs(pre_by_arm[arm], arm, seed_name)
            if item["scenario"] in {"chat", "memory"}
        }
        post_cases = {
            item["id"]: item
            for item in _arm_runs(post, arm, seed_name)
            if item["scenario"] in {"chat", "memory"}
        }
        if pre_cases.keys() != post_cases.keys():
            raise RuntimeError(f"P2-2 {arm} 臂修复前后 S+M 判例集合不一致")
        for case_id, pre_case in pre_cases.items():
            post_case = post_cases[case_id]
            repaired_first = bool(rng.getrandbits(1))
            blind_id = f"{arm}-{case_id}"
            review_rows.append(
                {
                    "blind_id": blind_id,
                    "arm": arm,
                    "case_id": case_id,
                    "scenario": pre_case["scenario"],
                    "turns": pre_case["turns"],
                    "option_a": post_case["replies"] if repaired_first else pre_case["replies"],
                    "option_b": pre_case["replies"] if repaired_first else post_case["replies"],
                    "preferred": None,
                    "reason": "",
                }
            )
            key_rows.append(
                {
                    "blind_id": blind_id,
                    "option_a": "repaired" if repaired_first else "pre_fix",
                    "option_b": "pre_fix" if repaired_first else "repaired",
                }
            )
    review = {
        "meta": {
            "version": "w3-p2-2-blind-v1",
            "seed_name": seed_name,
            "arms": ["A", "B"],
            "scenarios": ["chat", "memory"],
            "priority": "事实与诚实边界 > 对话自然度 > 陪伴感 > 冗余",
            "instructions": (
                "逐条在 preferred 填 A/B/平手，并在 reason 写一句理由；"
                "修复目标是不重复而非强求内容升级；完成与哈希校验前禁止打开映射表。"
            ),
        },
        "cases": review_rows,
    }
    key = {
        "meta": {
            "version": "w3-p2-2-blind-key-v1",
            "seed_name": seed_name,
            "shuffle_seed": shuffle_seed,
        },
        "mapping": key_rows,
    }
    return review, key


def main() -> int:
    """摘要：写出盲包、密钥和解盲前机械校验协议。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-a", type=Path, default=DEFAULT_PRE_A)
    parser.add_argument("--pre-b", type=Path, default=DEFAULT_PRE_B)
    parser.add_argument("--post", type=Path, default=DEFAULT_POST)
    parser.add_argument("--seed-name", default="seed42")
    parser.add_argument("--shuffle-seed", type=int, default=20261004)
    parser.add_argument("--packet-output", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--key-output", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--protocol-output", type=Path, default=DEFAULT_PROTOCOL)
    args = parser.parse_args()

    review, key = build_blind_review(
        {
            "A": _read_json(args.pre_a),
            "B": _read_json(args.pre_b),
        },
        _read_json(args.post),
        seed_name=args.seed_name,
        shuffle_seed=args.shuffle_seed,
    )
    _write_json(args.packet_output, review)
    _write_json(args.key_output, key)
    protocol = {
        "meta": {
            "version": "w3-p2-2-blind-protocol-v1",
            "status": "preregistered_before_review",
            "reviewer_count_required": 3,
            "minimum_valid_judges": 3,
            "invalid_below_minimum_action": "void_round_and_recruit_again",
        },
        "sources": {
            "pre_a": str(args.pre_a),
            "pre_a_sha256": _sha256(args.pre_a),
            "pre_b": str(args.pre_b),
            "pre_b_sha256": _sha256(args.pre_b),
            "post": str(args.post),
            "post_sha256": _sha256(args.post),
        },
        "sealed_material": {
            "packet": str(args.packet_output),
            "packet_sha256": _sha256(args.packet_output),
            "key": str(args.key_output),
            "key_sha256": _sha256(args.key_output),
        },
        "pre_unblind_checks": {
            "expected_case_count": len(review["cases"]),
            "all_preferences_completed": True,
            "all_reasons_non_empty": True,
            "packet_sha256_must_match": True,
            "key_must_remain_unopened": True,
        },
        "acceptance": {
            "single_turn": "A/B repaired outputs must not lose to their pre-fix arm overall",
            "multi_turn": "S16-S18 must not regress for either arm",
            "mechanical_gate_is_independent": True,
        },
    }
    _write_json(args.protocol_output, protocol)
    print(args.packet_output)
    print(args.key_output)
    print(args.protocol_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
