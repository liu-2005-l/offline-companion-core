"""拟人表述 W2 F2-c 双口径离线复检。

摘要：
    从冻结的 B 臂矩阵展开全部 370 条回复，分别验证运行时身份出口口径，
    以及检测器脱离身份意图触发门后的全量判据覆盖范围。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from offline_companion.core.persona_session.expression import (
    detect_identity_cliff,
    is_identity_intent,
)
from offline_companion.core.persona_session.session import (
    _ASSISTANT_NAME_QUESTION_KEYWORDS,
)
from persona_expression_metrics import char_ngrams, jaccard

DEFAULT_MATRIX = REPO_ROOT / "artifacts" / "persona_expression" / "w2_arm_b_matrix.json"
DEFAULT_PROBE = REPO_ROOT / "fixtures" / "persona_expression" / "w1_probe_turns.json"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "persona_expression" / "w2_f2c_offline_review.json"
STYLE_SCENARIOS = {"chat", "memory"}


def _sha256_text(text: str) -> str:
    """摘要：返回 UTF-8 文本的 SHA-256。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    """摘要：返回文件字节的 SHA-256。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_deterministic_identity_early_return(user: str, display_name: str) -> bool:
    """摘要：复刻既有身份查询早退的输入判据。

    参数：
        user: 冻结矩阵对应的原始用户输入。
        display_name: 矩阵运行时已解析的助手自称。
    返回值：
        在矩阵固定 memory_enabled=True 前提下是否走确定性身份直答。
    """
    text = user.strip()
    return bool(display_name) and any(keyword in text for keyword in _ASSISTANT_NAME_QUESTION_KEYWORDS)


def _base_row(
    *,
    source_kind: str,
    seed_name: str,
    item_id: str,
    turn: int,
    user: str,
    reply: str,
    display_name: str,
    output_source: str,
    identity_probe: bool,
) -> dict[str, Any]:
    """摘要：构造一条可同时供两个复检口径消费的明细。"""
    identity_intent = is_identity_intent(user)
    deterministic_early_return = _is_deterministic_identity_early_return(user, display_name)
    detector_verdict = detect_identity_cliff(reply, display_name)
    return {
        "source_kind": source_kind,
        "seed": seed_name,
        "item_id": item_id,
        "turn": turn,
        "user": user,
        "reply": reply,
        "reply_sha256": _sha256_text(reply),
        "identity_probe": identity_probe,
        "identity_intent": identity_intent,
        "deterministic_identity_early_return": deterministic_early_return,
        "generated_exit_eligible": identity_intent and not deterministic_early_return,
        "output_source": output_source,
        "detector_verdict": detector_verdict,
        "detector_score": int(detector_verdict),
        "four_gram_pairs": [],
        "four_gram_gate_population": False,
        "four_gram_positive_pair": False,
    }


def _expand_case_rows(arm: dict[str, Any], display_name: str) -> list[dict[str, Any]]:
    """摘要：展开三组判例数据，并标记逐轮 4-gram 相邻对贡献。"""
    rows: list[dict[str, Any]] = []
    for seed_name, run in arm["case_runs"].items():
        for case in run["cases"]:
            case_rows: list[dict[str, Any]] = []
            turns = list(case.get("turns", []))
            replies = list(case.get("replies", []))
            if len(turns) != len(replies):
                raise ValueError(f"{seed_name}/{case['id']} 的 turn/reply 数量不一致")
            for index, (turn_item, reply_value) in enumerate(zip(turns, replies, strict=True), start=1):
                case_rows.append(
                    _base_row(
                        source_kind="case",
                        seed_name=seed_name,
                        item_id=str(case["id"]),
                        turn=index,
                        user=str(turn_item["user"]),
                        reply=str(reply_value),
                        display_name=display_name,
                        output_source="direct",
                        identity_probe=False,
                    )
                )
            if str(case.get("scenario")) in STYLE_SCENARIOS:
                for row in case_rows:
                    row["four_gram_gate_population"] = len(case_rows) > 1
                for index in range(len(case_rows) - 1):
                    score = round(
                        jaccard(
                            char_ngrams(str(replies[index]), 4),
                            char_ngrams(str(replies[index + 1]), 4),
                        ),
                        6,
                    )
                    pair = {
                        "left_turn": index + 1,
                        "right_turn": index + 2,
                        "score": score,
                    }
                    case_rows[index]["four_gram_pairs"].append(pair)
                    case_rows[index + 1]["four_gram_pairs"].append(pair)
                    if score > 0:
                        case_rows[index]["four_gram_positive_pair"] = True
                        case_rows[index + 1]["four_gram_positive_pair"] = True
            rows.extend(case_rows)
    return rows


def _expand_probe_rows(
    arm: dict[str, Any],
    probe_fixture: dict[str, Any],
    display_name: str,
) -> list[dict[str, Any]]:
    """摘要：展开五组 50 轮 probe，并合并冻结的表达 trace。"""
    fixture_turns = list(probe_fixture["turns"])
    rows: list[dict[str, Any]] = []
    for seed_name, run in arm["probe_runs"].items():
        replies = list(run["replies"])
        traces = list(run.get("expression_traces", []))
        if len(fixture_turns) != len(replies) or len(replies) != len(traces):
            raise ValueError(f"{seed_name} 的 probe fixture/reply/trace 数量不一致")
        for fixture, reply_record, trace in zip(fixture_turns, replies, traces, strict=True):
            turn = int(fixture["turn"])
            if not isinstance(reply_record, dict):
                raise TypeError(f"{seed_name}/P{turn:02d} 的 probe reply 不是结构化记录")
            if int(reply_record.get("turn", -1)) != turn or str(reply_record.get("user")) != str(fixture["user"]):
                raise ValueError(f"{seed_name}/P{turn:02d} 的 probe 产物与 fixture 未对齐")
            rows.append(
                _base_row(
                    source_kind="probe",
                    seed_name=seed_name,
                    item_id=f"P{turn:02d}",
                    turn=turn,
                    user=str(fixture["user"]),
                    reply=str(reply_record["reply"]),
                    display_name=display_name,
                    output_source=str(trace.get("output_source") or "direct"),
                    identity_probe=bool(fixture.get("is_probe")),
                )
            )
    return rows


def build_review(matrix_path: Path, probe_path: Path) -> dict[str, Any]:
    """摘要：计算 F2-c 双口径复检结果。

    参数：
        matrix_path: 冻结的 W2 B 臂矩阵路径。
        probe_path: 预注册 50 轮 probe fixture 路径。
    返回值：
        含口径 a、口径 b、direct 拆分及逐条明细的审计对象。
    """
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    probe_fixture = json.loads(probe_path.read_text(encoding="utf-8"))
    arm = matrix["arms"]["B"]
    display_name = str(matrix["meta"]["display_name"])
    rows = _expand_case_rows(arm, display_name)
    rows.extend(_expand_probe_rows(arm, probe_fixture, display_name))
    if len(rows) != 370:
        raise ValueError(f"冻结矩阵应展开 370 条，实际 {len(rows)} 条")

    runtime_rows = [row for row in rows if row["generated_exit_eligible"]]
    runtime_true_rows = [row for row in runtime_rows if row["detector_verdict"]]
    full_true_rows = [row for row in rows if row["detector_verdict"]]
    identity_direct_rows = [
        row for row in rows if row["identity_probe"] and row["output_source"] == "direct"
    ]
    identity_early_rows = [row for row in identity_direct_rows if row["deterministic_identity_early_return"]]
    identity_generated_rows = [row for row in identity_direct_rows if not row["deterministic_identity_early_return"]]
    trigger_four_gram_rows = [row for row in full_true_rows if row["four_gram_positive_pair"]]
    trigger_four_gram_population_rows = [row for row in full_true_rows if row["four_gram_gate_population"]]

    return {
        "meta": {
            "version": "w2-f2c-v1",
            "source_matrix": str(matrix_path.relative_to(REPO_ROOT)),
            "source_matrix_sha256": _sha256_file(matrix_path),
            "probe_fixture": str(probe_path.relative_to(REPO_ROOT)),
            "probe_fixture_sha256": _sha256_file(probe_path),
            "display_name": display_name,
            "detector_score_semantics": "binary detector API: false=0, true=1",
            "runtime_scope": "identity_intent AND generated_exit; deterministic identity reply excluded",
            "full_scope": "all 370 replies without the runtime identity-intent gate",
            "four_gram_overlap_semantics": "triggered reply participates in a positive adjacent 4-gram pair",
        },
        "summary": {
            "total_reply_count": len(rows),
            "case_reply_count": sum(row["source_kind"] == "case" for row in rows),
            "probe_reply_count": sum(row["source_kind"] == "probe" for row in rows),
            "identity_intent_count": sum(row["identity_intent"] for row in rows),
            "deterministic_identity_early_return_count": sum(
                row["deterministic_identity_early_return"] for row in rows
            ),
        },
        "scope_a_runtime_fidelity": {
            "eligible_count": len(runtime_rows),
            "verdict_false_count": len(runtime_rows) - len(runtime_true_rows),
            "verdict_true_count": len(runtime_true_rows),
            "z_reopened": bool(runtime_true_rows),
            "interpretation": (
                "存在离线 true；若冻结运行时仍为 direct，则 Z 复活并需立案"
                if runtime_true_rows
                else "全部 verdict=false；运行时 clean direct 行为如实，Z 暂时排除"
            ),
            "details": runtime_rows,
        },
        "scope_b_full_coverage": {
            "evaluated_count": len(rows),
            "verdict_false_count": len(rows) - len(full_true_rows),
            "verdict_true_count": len(full_true_rows),
            "trigger_rate": round(len(full_true_rows) / len(rows), 6),
            "triggered_case_count": sum(row["source_kind"] == "case" for row in full_true_rows),
            "triggered_probe_count": sum(row["source_kind"] == "probe" for row in full_true_rows),
            "four_gram_gate_population_trigger_count": len(trigger_four_gram_population_rows),
            "four_gram_positive_overlap_count": len(trigger_four_gram_rows),
            "four_gram_positive_overlap_rate": (
                round(len(trigger_four_gram_rows) / len(full_true_rows), 6) if full_true_rows else 0.0
            ),
            "interpretation": (
                "检测器全量仍零触发，与 4-gram gate 完全不同域"
                if not full_true_rows
                else (
                    "检测器存在触发，但触发全部位于 probe、未进入 4-gram gate 统计总体；"
                    "对 gate 红形态无重合，两个判据域不对齐"
                    if not trigger_four_gram_population_rows
                    else "检测器全量存在触发；需结合逐条 4-gram 重合明细评估扩展价值"
                )
            ),
            "triggered_details": full_true_rows,
        },
        "identity_probe_direct_split": {
            "direct_count": len(identity_direct_rows),
            "deterministic_identity_early_return_count": len(identity_early_rows),
            "generated_exit_direct_count": len(identity_generated_rows),
            "generated_exit_detector_eligible_count": sum(
                row["generated_exit_eligible"] for row in identity_generated_rows
            ),
            "deterministic_details": identity_early_rows,
            "generated_details": identity_generated_rows,
        },
        "all_details": rows,
    }


def main() -> int:
    """摘要：解析参数、执行复检并写入 JSON 证据。"""
    parser = argparse.ArgumentParser(description="运行拟人表述 W2 F2-c 双口径离线复检")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    review = build_review(args.matrix.resolve(), args.probe.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **review["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
