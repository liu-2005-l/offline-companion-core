"""摘要：校验并机械聚合 W3 R0 guard 三席盲评结果。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "persona_expression"
MANIFEST_PATH = ARTIFACT_ROOT / "w3_closure_r0_guard_blind_sampling_manifest.json"
PRE_UNBLIND_PATH = (
    ARTIFACT_ROOT / "w3_closure_r0_guard_blind_pre_unblind_validation.json"
)
AGGREGATE_PATH = ARTIFACT_ROOT / "w3_closure_r0_guard_blind_aggregate.json"
REVIEW_PATHS = {
    "prompt_side": ARTIFACT_ROOT / "w3_closure_r0_guard_blind_review_prompt_side.json",
    "context_free_ai_1": ARTIFACT_ROOT
    / "w3_closure_r0_guard_blind_review_context_free_ai_1.json",
    "context_free_ai_2": ARTIFACT_ROOT
    / "w3_closure_r0_guard_blind_review_context_free_ai_2.json",
}


class BlindAggregationError(RuntimeError):
    """摘要：表示盲评材料校验或解盲聚合违反冻结协议。"""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BlindAggregationError(f"JSON 无法读取：{path}") from exc
    if not isinstance(payload, dict):
        raise BlindAggregationError(f"JSON 顶层必须是对象：{path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _repo_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _validate_review(
    reviewer_id: str,
    packet: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    packet_rows = packet.get("pairs")
    review_rows = review.get("results")
    if not isinstance(packet_rows, list) or not isinstance(review_rows, list):
        raise BlindAggregationError(f"packet/review rows 缺失：{reviewer_id}")
    packet_ids = [row.get("pair_id") for row in packet_rows]
    review_ids = [row.get("pair_id") for row in review_rows]
    if len(packet_ids) != 36 or len(set(packet_ids)) != 36:
        raise BlindAggregationError(f"packet pair_id 不完整：{reviewer_id}")
    if review_ids != packet_ids:
        raise BlindAggregationError(f"review 顺序或 pair_id 不匹配：{reviewer_id}")
    counts: Counter[str] = Counter()
    for row in review_rows:
        choice = row.get("choice")
        reason = row.get("reason")
        if choice not in {"A", "B", "tie"}:
            raise BlindAggregationError(f"choice 非法：{reviewer_id}/{row.get('pair_id')}")
        if choice != "tie" and (not isinstance(reason, str) or not reason.strip()):
            raise BlindAggregationError(
                f"非平手理由缺失：{reviewer_id}/{row.get('pair_id')}"
            )
        counts[choice] += 1
    return {
        "reviewer": reviewer_id,
        "pair_count": len(review_rows),
        "choice_counts": dict(counts),
    }


def build_pre_unblind_validation(
    manifest: dict[str, Any],
    packets: dict[str, dict[str, Any]],
    reviews: dict[str, dict[str, Any]],
    *,
    packet_paths: dict[str, Path],
    review_paths: dict[str, Path],
    key_path: Path,
) -> dict[str, Any]:
    """摘要：不解析 key，仅核验封包、key 字节哈希与三席完整性。

    参数：
        manifest: 抽样 manifest。
        packets: 三席匿名 packet。
        reviews: 三席原始结果。
        packet_paths: packet 实际路径。
        review_paths: review 实际路径。
        key_path: 仅用于字节哈希的隔离 key 路径。

    返回值：
        可在解盲前公开的机械校验记录。
    """

    manifest_packets = {
        row["reviewer"]: row for row in manifest.get("packets", [])
    }
    reviewer_checks: list[dict[str, Any]] = []
    for reviewer_id in REVIEW_PATHS:
        manifest_packet = manifest_packets.get(reviewer_id)
        if not isinstance(manifest_packet, dict):
            raise BlindAggregationError(f"manifest packet 缺失：{reviewer_id}")
        packet_sha256 = _sha256(packet_paths[reviewer_id])
        if packet_sha256 != manifest_packet.get("sha256"):
            raise BlindAggregationError(f"packet SHA 不匹配：{reviewer_id}")
        check = _validate_review(
            reviewer_id,
            packets[reviewer_id],
            reviews[reviewer_id],
        )
        check.update(
            {
                "packet_path": _repo_path(packet_paths[reviewer_id]),
                "packet_sha256": packet_sha256,
                "review_path": _repo_path(review_paths[reviewer_id]),
                "review_sha256": _sha256(review_paths[reviewer_id]),
            }
        )
        reviewer_checks.append(check)

    key_sha256 = _sha256(key_path)
    sealed_key = manifest.get("sealed_key")
    if not isinstance(sealed_key, dict) or key_sha256 != sealed_key.get("sha256"):
        raise BlindAggregationError("key SHA 不匹配")
    return {
        "meta": {
            "version": "w3-closure-r0-guard-pre-unblind-validation-v1",
            "status": "valid_before_unblind",
            "key_content_parsed": False,
            "protocol_anchor_commit": manifest["meta"]["protocol_anchor_commit"],
        },
        "reviewers": reviewer_checks,
        "sealed_key": {
            "path": _repo_path(key_path),
            "sha256": key_sha256,
            "content_parsed": False,
        },
        "all_packet_hashes_match": True,
        "all_reviewers_complete": True,
        "ready_to_unblind": True,
    }


def _majority(votes: list[str]) -> str:
    counts = Counter(votes)
    choice, count = counts.most_common(1)[0]
    return choice if count >= 2 else "split"


def aggregate_unblinded(
    reviews: dict[str, dict[str, Any]],
    key: dict[str, Any],
) -> dict[str, Any]:
    """摘要：用隔离映射把三席 A/B/tie 机械转换为来源方向并聚合。

    参数：
        reviews: 已完成且通过解盲前校验的三席结果。
        key: 哈希已核验的隔离映射。

    返回值：
        逐对来源票、分层汇总和偏差台账。
    """

    key_reviewers = key.get("reviewers")
    if not isinstance(key_reviewers, dict):
        raise BlindAggregationError("key reviewers 缺失")
    review_maps = {
        reviewer_id: {row["pair_id"]: row for row in review["results"]}
        for reviewer_id, review in reviews.items()
    }
    key_maps = {
        reviewer_id: {row["pair_id"]: row for row in rows}
        for reviewer_id, rows in key_reviewers.items()
    }
    pair_ids = sorted(review_maps["prompt_side"])
    pair_rows: list[dict[str, Any]] = []
    deviations: list[dict[str, Any]] = []
    for pair_id in pair_ids:
        votes: list[dict[str, Any]] = []
        strata: set[str] = set()
        identities: set[tuple[Any, ...]] = set()
        for reviewer_id in REVIEW_PATHS:
            review_row = review_maps[reviewer_id][pair_id]
            key_row = key_maps[reviewer_id][pair_id]
            strata.add(key_row["stratum"])
            identities.add(
                (
                    key_row["seed"],
                    key_row["scenario_id"],
                    key_row["turn_index"],
                )
            )
            blind_choice = review_row["choice"]
            source_choice = (
                "tie"
                if blind_choice == "tie"
                else key_row[f"reply_{blind_choice}_source"]
            )
            votes.append(
                {
                    "reviewer": reviewer_id,
                    "blind_choice": blind_choice,
                    "source_choice": source_choice,
                    "reason": review_row.get("reason", ""),
                }
            )
        if len(strata) != 1 or len(identities) != 1:
            raise BlindAggregationError(f"跨席 key 元数据不一致：{pair_id}")
        stratum = next(iter(strata))
        seed, scenario_id, turn_index = next(iter(identities))
        majority = _majority([vote["source_choice"] for vote in votes])
        expected = "tie" if stratum == "single_turn_no_spill" else "repaired"
        conforms = majority == expected
        pair_row = {
            "pair_id": pair_id,
            "stratum": stratum,
            "seed": seed,
            "scenario_id": scenario_id,
            "turn_index": turn_index,
            "votes": votes,
            "majority": majority,
            "expected": expected,
            "conforms": conforms,
        }
        pair_rows.append(pair_row)
        if not conforms:
            deviations.append(
                {
                    "pair_id": pair_id,
                    "stratum": stratum,
                    "majority": majority,
                    "expected": expected,
                    "status": "requires_attribution",
                }
            )

    stratum_summary: dict[str, dict[str, int]] = {}
    for stratum in ("single_turn_no_spill", "multi_turn_repair"):
        outcomes = Counter(
            row["majority"] for row in pair_rows if row["stratum"] == stratum
        )
        stratum_summary[stratum] = dict(outcomes)
    return {
        "pairs": pair_rows,
        "summary": {
            "pair_count": len(pair_rows),
            "strata": stratum_summary,
            "conforming_pairs": sum(row["conforms"] for row in pair_rows),
            "deviation_count": len(deviations),
            "statistical_significance_claimed": False,
        },
        "deviation_ledger": deviations,
    }


def _load_materials() -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Path],
]:
    manifest = _load_json(MANIFEST_PATH)
    packet_paths = {
        row["reviewer"]: REPO_ROOT / row["path"] for row in manifest["packets"]
    }
    packets = {
        reviewer_id: _load_json(path) for reviewer_id, path in packet_paths.items()
    }
    reviews = {
        reviewer_id: _load_json(path) for reviewer_id, path in REVIEW_PATHS.items()
    }
    return manifest, packets, reviews, packet_paths


def main() -> int:
    """摘要：执行解盲前校验，或在校验通过后机械解盲。"""

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--unblind", action="store_true")
    args = parser.parse_args()

    manifest, packets, reviews, packet_paths = _load_materials()
    key_path = REPO_ROOT / manifest["sealed_key"]["path"]
    validation = build_pre_unblind_validation(
        manifest,
        packets,
        reviews,
        packet_paths=packet_paths,
        review_paths=REVIEW_PATHS,
        key_path=key_path,
    )
    if args.validate_only:
        _write_json(PRE_UNBLIND_PATH, validation)
        print(PRE_UNBLIND_PATH.relative_to(REPO_ROOT).as_posix())
        return 0

    stored_validation = _load_json(PRE_UNBLIND_PATH)
    if stored_validation != validation or validation["meta"]["status"] != "valid_before_unblind":
        raise BlindAggregationError("解盲前校验记录缺失或材料已变化")
    key = _load_json(key_path)
    aggregate = aggregate_unblinded(reviews, key)
    aggregate["meta"] = {
        "version": "w3-closure-r0-guard-blind-aggregate-v1",
        "status": "unblinded_descriptive_aggregation_complete",
        "protocol_anchor_commit": manifest["meta"]["protocol_anchor_commit"],
        "pre_unblind_validation": _repo_path(PRE_UNBLIND_PATH),
        "key_sha256": validation["sealed_key"]["sha256"],
    }
    aggregate["reviewer_disclosures"] = {
        reviewer_id: review.get("meta", {}).get("disclosure", [])
        for reviewer_id, review in reviews.items()
    }
    aggregate["scope_observations"] = reviews["prompt_side"].get("observations", [])
    _write_json(AGGREGATE_PATH, aggregate)
    print(AGGREGATE_PATH.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
