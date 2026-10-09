"""摘要：按冻结协议生成 R0 guard 三席盲包、隔离 key 与抽样清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "persona_expression"
PROTOCOL_PATH = ARTIFACT_ROOT / "w3_closure_r0_guard_blind_protocol.json"
KEY_PATH = ARTIFACT_ROOT / "w3_closure_r0_guard_blind_key.json"
MANIFEST_PATH = ARTIFACT_ROOT / "w3_closure_r0_guard_blind_sampling_manifest.json"
REVIEWER_IDS = ("prompt_side", "context_free_ai_1", "context_free_ai_2")
PACKET_PATHS = {
    reviewer_id: ARTIFACT_ROOT / f"w3_closure_r0_guard_blind_{reviewer_id}.json"
    for reviewer_id in REVIEWER_IDS
}


class BlindSamplingError(RuntimeError):
    """摘要：表示冻结来源或盲包抽样违反预注册协议。"""


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(*parts: object) -> str:
    joined = "\0".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _git_output(*args: str) -> bytes:
    process = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise BlindSamplingError(f"git 命令失败：git {' '.join(args)}；{detail}")
    return process.stdout


def _resolve_commit(revision: str) -> str:
    commit = _git_output("rev-parse", f"{revision}^{{commit}}").decode("ascii").strip()
    if not commit:
        raise BlindSamplingError(f"commit 解析为空：{revision}")
    return commit


def _git_blob(commit: str, relative_path: str) -> bytes:
    normalized = Path(relative_path).as_posix()
    return _git_output("show", f"{commit}:{normalized}")


def _load_json_bytes(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BlindSamplingError(f"JSON 无法读取：{label}") from exc
    if not isinstance(payload, dict):
        raise BlindSamplingError(f"JSON 顶层必须是对象：{label}")
    return payload


def _audit_path(matrix_path: str) -> str:
    if not matrix_path.endswith(".json"):
        raise BlindSamplingError(f"矩阵路径后缀非法：{matrix_path}")
    return f"{matrix_path[:-5]}.audit.json"


def _validate_audit(
    audit: dict[str, Any],
    matrix_bytes: bytes,
    *,
    generation_commit: str,
    label: str,
) -> dict[str, str]:
    meta = audit.get("meta")
    checkpoints = audit.get("checkpoints")
    if audit.get("audit_schema") != 1 or not isinstance(meta, dict):
        raise BlindSamplingError(f"audit schema 非冻结版本：{label}")
    if meta.get("provenance_complete") is not True:
        raise BlindSamplingError(f"audit provenance 不完整：{label}")
    audit_matrix_sha256 = str(meta.get("matrix_sha256", "")).lower()
    git_blob_sha256 = hashlib.sha256(matrix_bytes).hexdigest()
    crlf_sha256 = hashlib.sha256(matrix_bytes.replace(b"\n", b"\r\n")).hexdigest()
    if audit_matrix_sha256 == git_blob_sha256:
        hash_match_mode = "exact_git_blob"
    elif audit_matrix_sha256 == crlf_sha256:
        hash_match_mode = "git_lf_to_generation_crlf"
    else:
        raise BlindSamplingError(f"audit matrix_sha256 不匹配：{label}")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise BlindSamplingError(f"audit checkpoint 为空：{label}")
    for checkpoint in checkpoints:
        provenance = checkpoint.get("provenance") if isinstance(checkpoint, dict) else None
        if not isinstance(provenance, dict):
            raise BlindSamplingError(f"checkpoint provenance 缺失：{label}")
        if provenance.get("git_commit") != generation_commit:
            raise BlindSamplingError(f"checkpoint commit 漂移：{label}")
    return {
        "audit_matrix_sha256": audit_matrix_sha256.upper(),
        "git_blob_sha256": git_blob_sha256.upper(),
        "hash_match_mode": hash_match_mode,
    }


def _validate_arm_config(
    matrix: dict[str, Any],
    expected: dict[str, Any],
    *,
    label: str,
) -> None:
    try:
        actual = matrix["arms"][expected["arm"]]["config"]
    except (KeyError, TypeError) as exc:
        raise BlindSamplingError(f"矩阵 arm/config 缺失：{label}") from exc
    for key in (
        "cross_turn_repetition_guard_enabled",
        "identity_near_prompt_enabled",
    ):
        if actual.get(key) is not expected[key]:
            raise BlindSamplingError(f"矩阵配置不匹配：{label}:{key}")


def _seed_value(seed_name: str) -> int:
    if not seed_name.startswith("seed"):
        raise BlindSamplingError(f"seed 键非法：{seed_name}")
    try:
        return int(seed_name.removeprefix("seed"))
    except ValueError as exc:
        raise BlindSamplingError(f"seed 键非法：{seed_name}") from exc


def _case_map(run: dict[str, Any], *, label: str) -> dict[str, dict[str, Any]]:
    cases = run.get("cases")
    if not isinstance(cases, list):
        raise BlindSamplingError(f"cases 缺失：{label}")
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        case_id = case.get("id") if isinstance(case, dict) else None
        if not isinstance(case_id, str) or not case_id or case_id in result:
            raise BlindSamplingError(f"case id 非法或重复：{label}")
        result[case_id] = case
    return result


def _context(case: dict[str, Any], turn_index: int) -> list[dict[str, str]]:
    turns = case.get("turns")
    replies = case.get("replies")
    if not isinstance(turns, list) or not isinstance(replies, list):
        raise BlindSamplingError("case turns/replies 缺失")
    if len(turns) != len(replies) or not 0 <= turn_index < len(turns):
        raise BlindSamplingError("case turns/replies 数量不一致")
    messages: list[dict[str, str]] = []
    for index in range(turn_index + 1):
        user_text = turns[index].get("user") if isinstance(turns[index], dict) else None
        if not isinstance(user_text, str):
            raise BlindSamplingError("turn user 文本缺失")
        messages.append({"role": "user", "content": user_text})
        if index < turn_index:
            reply = replies[index]
            if not isinstance(reply, str):
                raise BlindSamplingError("历史 assistant 文本缺失")
            messages.append({"role": "assistant", "content": reply})
    return messages


def _build_joined_turns(
    protocol: dict[str, Any],
    w2_matrix: dict[str, Any],
    p2_matrix: dict[str, Any],
) -> list[dict[str, Any]]:
    source = protocol["frozen_sources"]
    w2_runs = w2_matrix["arms"][source["w2_matrix"]["arm"]]["case_runs"]
    p2_runs = p2_matrix["arms"][source["p2_matrix"]["arm"]]["case_runs"]
    if set(w2_runs) != set(p2_runs):
        raise BlindSamplingError("W2/P2 seed 集合不一致")

    rows: list[dict[str, Any]] = []
    for seed_name in sorted(w2_runs, key=_seed_value):
        seed = _seed_value(seed_name)
        w2_cases = _case_map(w2_runs[seed_name], label=f"W2:{seed_name}")
        p2_cases = _case_map(p2_runs[seed_name], label=f"P2:{seed_name}")
        if set(w2_cases) != set(p2_cases):
            raise BlindSamplingError(f"W2/P2 case 集合不一致：{seed_name}")
        for scenario_id in sorted(w2_cases):
            w2_case = w2_cases[scenario_id]
            p2_case = p2_cases[scenario_id]
            w2_replies = w2_case.get("replies")
            p2_replies = p2_case.get("replies")
            p2_traces = p2_case.get("repetition_traces")
            if not isinstance(w2_replies, list) or not isinstance(p2_replies, list):
                raise BlindSamplingError(f"reply 列表缺失：{seed_name}/{scenario_id}")
            if len(w2_replies) != len(p2_replies) or not isinstance(p2_traces, list):
                raise BlindSamplingError(f"reply/trace 数量不一致：{seed_name}/{scenario_id}")
            if len(p2_traces) != len(p2_replies):
                raise BlindSamplingError(f"P2 trace 数量不一致：{seed_name}/{scenario_id}")
            for turn_index, (w2_reply, p2_reply) in enumerate(
                zip(w2_replies, p2_replies, strict=True)
            ):
                w2_context = _context(w2_case, turn_index)
                p2_context = _context(p2_case, turn_index)
                if _canonical_bytes(w2_context) != _canonical_bytes(p2_context):
                    raise BlindSamplingError(
                        f"上下文不一致：{seed_name}/{scenario_id}/{turn_index}"
                    )
                rows.append(
                    {
                        "seed": seed,
                        "scenario_id": scenario_id,
                        "turn_index": turn_index,
                        "turn_count": len(w2_replies),
                        "context": w2_context,
                        "pre_fix": w2_reply,
                        "repaired": p2_reply,
                        "repetition_trace": p2_traces[turn_index],
                    }
                )
    return rows


def _validate_single_turn(row: dict[str, Any]) -> None:
    if row["pre_fix"].encode("utf-8") != row["repaired"].encode("utf-8"):
        raise BlindSamplingError(
            f"单轮文本非逐字节一致：{row['seed']}/{row['scenario_id']}"
        )
    trace = row["repetition_trace"]
    first = trace.get("first") if isinstance(trace, dict) else None
    if (
        not isinstance(first, dict)
        or trace.get("outcome") != "bypass"
        or first.get("reason") != "missing_previous_or_current_reply"
        or trace.get("retry_taken") is not False
    ):
        raise BlindSamplingError(
            f"单轮旁路形态异常：{row['seed']}/{row['scenario_id']}"
        )


def _select_rows(
    protocol: dict[str, Any],
    joined_rows: list[dict[str, Any]],
    *,
    protocol_anchor_commit: str,
) -> list[dict[str, Any]]:
    construction = protocol["sample_construction"]
    single_rows = [row for row in joined_rows if row["turn_count"] == 1]
    for row in single_rows:
        _validate_single_turn(row)

    expected_scenarios = construction["single_turn_no_spill"][
        "current_scenario_ids"
    ]
    actual_scenarios = sorted({row["scenario_id"] for row in single_rows})
    if set(actual_scenarios) != set(expected_scenarios):
        raise BlindSamplingError("单轮 scenario 集合与冻结协议不一致")
    if len(single_rows) != construction["single_turn_no_spill"][
        "current_candidate_turn_count"
    ]:
        raise BlindSamplingError("单轮候选数量与冻结协议不一致")

    selected_single: list[dict[str, Any]] = []
    for scenario_id in expected_scenarios:
        candidates = [row for row in single_rows if row["scenario_id"] == scenario_id]
        selected_single.append(
            min(
                candidates,
                key=lambda row: _digest(
                    protocol_anchor_commit,
                    scenario_id,
                    row["seed"],
                    row["turn_index"],
                ),
            )
        )

    differing_multi = [
        row
        for row in joined_rows
        if row["turn_count"] > 1 and row["pre_fix"] != row["repaired"]
    ]
    for row in differing_multi:
        trace = row["repetition_trace"]
        first = trace.get("first") if isinstance(trace, dict) else None
        if (
            not isinstance(first, dict)
            or first.get("reason") != "threshold_matched"
            or trace.get("retry_taken") is not True
            or trace.get("outcome") not in {"retry", "fallback"}
        ):
            raise BlindSamplingError(
                f"多轮差异缺少 guard 触发链：{row['seed']}/{row['scenario_id']}/"
                f"{row['turn_index']}"
            )
    priority = {"M09-M10": 0, "S16-S18": 1}
    differing_multi.sort(
        key=lambda row: (
            priority.get(row["scenario_id"], 2),
            row["seed"],
            row["turn_index"],
        )
    )
    expected_multi = construction["multi_turn_repair"]["current_expected_keys"]
    actual_multi = [
        {
            "seed": row["seed"],
            "scenario_id": row["scenario_id"],
            "turn_index": row["turn_index"],
        }
        for row in differing_multi
    ]
    if actual_multi != expected_multi:
        raise BlindSamplingError("多轮差异集合与冻结协议不一致")

    selected: list[dict[str, Any]] = []
    selected.extend({**row, "stratum": "multi_turn_repair"} for row in differing_multi)
    selected.extend({**row, "stratum": "single_turn_no_spill"} for row in selected_single)
    expected_n = construction["current_expected_n"]
    if len(selected) != expected_n:
        raise BlindSamplingError("最终样本量与冻结协议不一致")

    pair_order = sorted(
        selected,
        key=lambda row: _digest(
            protocol_anchor_commit,
            "pair-id",
            row["seed"],
            row["scenario_id"],
            row["turn_index"],
        ),
    )
    for index, row in enumerate(pair_order, start=1):
        row["pair_id"] = f"G{index:03d}"
    return pair_order


def build_sampling_materials(
    protocol: dict[str, Any],
    w2_matrix: dict[str, Any],
    p2_matrix: dict[str, Any],
    *,
    protocol_anchor_commit: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """摘要：按冻结规则构造三席匿名包与隔离映射。

    参数：
        protocol: 锚定协议对象。
        w2_matrix: guard-off 的 W2 B 臂矩阵。
        p2_matrix: guard-on 的 P2 B 臂矩阵。
        protocol_anchor_commit: 首次包含协议精确字节的 commit。

    返回值：
        三席 packet、隔离 key 与不含映射内容的抽样摘要。
    """

    selected = _select_rows(
        protocol,
        _build_joined_turns(protocol, w2_matrix, p2_matrix),
        protocol_anchor_commit=protocol_anchor_commit,
    )
    if len(selected) % 2:
        raise BlindSamplingError("严格左右平衡要求偶数样本量")

    packets: dict[str, dict[str, Any]] = {}
    key_reviewers: dict[str, list[dict[str, Any]]] = {}
    for reviewer_id in REVIEWER_IDS:
        position_rank = sorted(
            selected,
            key=lambda row: _digest(
                protocol_anchor_commit,
                "position",
                reviewer_id,
                row["pair_id"],
            ),
        )
        repaired_on_a = {
            row["pair_id"] for row in position_rank[: len(position_rank) // 2]
        }
        packet_rows: list[dict[str, Any]] = []
        key_rows: list[dict[str, Any]] = []
        for row in selected:
            repaired_first = row["pair_id"] in repaired_on_a
            packet_rows.append(
                {
                    "pair_id": row["pair_id"],
                    "context": row["context"],
                    "reply_A": row["repaired"] if repaired_first else row["pre_fix"],
                    "reply_B": row["pre_fix"] if repaired_first else row["repaired"],
                }
            )
            key_rows.append(
                {
                    "pair_id": row["pair_id"],
                    "stratum": row["stratum"],
                    "seed": row["seed"],
                    "scenario_id": row["scenario_id"],
                    "turn_index": row["turn_index"],
                    "reply_A_source": "repaired" if repaired_first else "pre_fix",
                    "reply_B_source": "pre_fix" if repaired_first else "repaired",
                }
            )
        packet_rows.sort(
            key=lambda row: _digest(
                protocol_anchor_commit,
                "order",
                reviewer_id,
                row["pair_id"],
            )
        )
        packets[reviewer_id] = {
            "meta": {
                "version": "w3-closure-r0-guard-blind-packet-v1",
                "reviewer": reviewer_id,
                "protocol_anchor_commit": protocol_anchor_commit,
                "pair_count": len(packet_rows),
                "choices": ["A", "B", "tie"],
                "instructions": (
                    "仅依据匿名对子文本判断。逐对选择 A、B 或 tie；"
                    "选择 A/B 时必须另行填写理由，逐字相同或无法区分时选择 tie。"
                ),
            },
            "pairs": packet_rows,
        }
        key_reviewers[reviewer_id] = sorted(key_rows, key=lambda row: row["pair_id"])

    key = {
        "meta": {
            "version": "w3-closure-r0-guard-blind-key-v1",
            "protocol_anchor_commit": protocol_anchor_commit,
        },
        "reviewers": key_reviewers,
    }
    summary = {
        "pair_count": len(selected),
        "stratum_counts": {
            "multi_turn_repair": sum(
                row["stratum"] == "multi_turn_repair" for row in selected
            ),
            "single_turn_no_spill": sum(
                row["stratum"] == "single_turn_no_spill" for row in selected
            ),
        },
        "reviewer_count": len(packets),
    }
    return packets, key, summary


def _write_json(path: Path, payload: dict[str, Any]) -> bytes:
    data = _json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def main() -> int:
    """摘要：验证冻结 blob 后现场生成三席 packet、key 与 manifest。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol-anchor-commit", required=True)
    args = parser.parse_args()

    protocol_anchor_commit = _resolve_commit(args.protocol_anchor_commit)
    protocol_relative = PROTOCOL_PATH.relative_to(REPO_ROOT).as_posix()
    protocol_bytes = _git_blob(protocol_anchor_commit, protocol_relative)
    protocol = _load_json_bytes(protocol_bytes, label=protocol_relative)
    if protocol.get("meta", {}).get("status") != "frozen_preregistered_before_sampling":
        raise BlindSamplingError("协议状态不是 frozen_preregistered_before_sampling")

    source = protocol["frozen_sources"]
    artifact_commit = _resolve_commit(source["artifact_commit"])
    generation_commit = _resolve_commit(source["generation_commit"])
    source_payloads: dict[str, dict[str, Any]] = {}
    source_manifest: dict[str, dict[str, str]] = {}
    for label in ("w2_matrix", "p2_matrix"):
        declaration = source[label]
        matrix_path = declaration["path"]
        matrix_bytes = _git_blob(artifact_commit, matrix_path)
        audit_path = _audit_path(matrix_path)
        audit_bytes = _git_blob(artifact_commit, audit_path)
        matrix = _load_json_bytes(matrix_bytes, label=matrix_path)
        audit = _load_json_bytes(audit_bytes, label=audit_path)
        audit_validation = _validate_audit(
            audit,
            matrix_bytes,
            generation_commit=generation_commit,
            label=label,
        )
        _validate_arm_config(matrix, declaration, label=label)
        source_payloads[label] = matrix
        source_manifest[label] = {
            "path": matrix_path,
            "sha256": _sha256(matrix_bytes),
            "audit_path": audit_path,
            "audit_sha256": _sha256(audit_bytes),
            "audit_matrix_sha256": audit_validation["audit_matrix_sha256"],
            "audit_hash_match_mode": audit_validation["hash_match_mode"],
        }

    packets, key, summary = build_sampling_materials(
        protocol,
        source_payloads["w2_matrix"],
        source_payloads["p2_matrix"],
        protocol_anchor_commit=protocol_anchor_commit,
    )
    packet_manifest: list[dict[str, Any]] = []
    for reviewer_id, packet in packets.items():
        packet_path = PACKET_PATHS[reviewer_id]
        packet_bytes = _write_json(packet_path, packet)
        packet_manifest.append(
            {
                "reviewer": reviewer_id,
                "path": packet_path.relative_to(REPO_ROOT).as_posix(),
                "sha256": _sha256(packet_bytes),
                "pair_count": len(packet["pairs"]),
            }
        )
    key_bytes = _write_json(KEY_PATH, key)
    manifest = {
        "meta": {
            "version": "w3-closure-r0-guard-blind-sampling-manifest-v1",
            "status": "sampled_before_review",
            "protocol_anchor_commit": protocol_anchor_commit,
            "artifact_commit": artifact_commit,
            "generation_commit": generation_commit,
            "sampling_tool_path": Path(__file__).relative_to(REPO_ROOT).as_posix(),
            "sampling_tool_sha256": _sha256(Path(__file__).read_bytes()),
        },
        "protocol": {
            "path": protocol_relative,
            "sha256": _sha256(protocol_bytes),
        },
        "sources": source_manifest,
        "sample": summary,
        "packets": packet_manifest,
        "sealed_key": {
            "path": KEY_PATH.relative_to(REPO_ROOT).as_posix(),
            "sha256": _sha256(key_bytes),
            "git_state_required": "untracked_and_gitignored_until_unblind",
        },
        "pre_unblind_checks": {
            "all_packet_hashes_must_match": True,
            "key_hash_must_match": True,
            "all_reviewers_complete_all_pairs": True,
            "key_must_remain_untracked": True,
        },
    }
    _write_json(MANIFEST_PATH, manifest)
    print(MANIFEST_PATH.relative_to(REPO_ROOT).as_posix())
    for packet_path in PACKET_PATHS.values():
        print(packet_path.relative_to(REPO_ROOT).as_posix())
    print(KEY_PATH.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
