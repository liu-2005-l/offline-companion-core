"""摘要：运行 W3-P2-2 A/B 三 seed 复测并生成复读门验收证据。"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
SCRIPT_ROOT = Path(__file__).resolve().parent
for import_root in (SRC_ROOT, SCRIPT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from offline_companion.core.persona_constraint import load_persona_constraint_assets
from offline_companion.core.persona_session.expression import PersonaExpressionConfig
from offline_companion.core.persona_session.repetition_guard import (
    CROSS_TURN_REPETITION_RUNTIME_THRESHOLD,
    cross_turn_repetition_score,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import (
    append_message,
    connect,
    new_session,
    recent_messages,
)
from persona_expression_metrics import calculate_metrics
from run_persona_expression_w1_b1 import CASE_SEEDS, _comma_ints
from run_persona_expression_w1_baseline import (
    DEFAULT_CASES,
    DEFAULT_PERSONA,
    _assert_memory_injection_live,
    _build_backend,
    _git_commit,
    _load_persona,
    _seed_memory,
)
from run_persona_expression_w2 import _exclusive_run_lock, _metric_distribution

DEFAULT_VALIDATION_CASES = (
    REPO_ROOT / "fixtures" / "persona_expression" / "w3_p2_2_validation_cases.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "persona_expression" / "w3_p2_2_ab_matrix.json"
DEFAULT_TRIGGER_OUTPUT = (
    REPO_ROOT / "artifacts" / "persona_expression" / "w3_p2_2_trigger_samples.json"
)
DEFAULT_CHECKPOINT_DIR = (
    REPO_ROOT / "artifacts" / "persona_expression" / "w3_p2_2_checkpoints"
)
DEFAULT_LOCK_FILE = REPO_ROOT / "artifacts" / "persona_expression" / "w3_p2_2.lock"
GLOBAL_GATE = 0.0368
LOCAL_RETRY_GATE = 0.02


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """摘要：以稳定 UTF-8 形态写出 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    """摘要：返回文件内容的大写 SHA-256。"""

    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _arm_config(arm: str) -> PersonaExpressionConfig:
    """摘要：返回开启复读门的冻结 A/B 变体配置。"""

    if arm == "A":
        return PersonaExpressionConfig(
            style_examples_enabled=True,
            cross_turn_repetition_guard_enabled=True,
        )
    if arm == "B":
        return PersonaExpressionConfig(
            style_examples_enabled=True,
            identity_near_prompt_enabled=True,
            cross_turn_repetition_guard_enabled=True,
        )
    raise ValueError(f"未知 P2-2 arm: {arm}")


def _run_case(
    *,
    case: dict[str, Any],
    memory_bundle: list[dict[str, Any]],
    persona: Any,
    backend: Any,
    constraint_assets: Any,
    temp_root: Path,
    max_tokens: int,
    expression_config: PersonaExpressionConfig,
) -> dict[str, Any]:
    """摘要：运行单个隔离会话并保留逐轮 repetition/L4 trace。"""

    session_id = f"w3-p2-2-{case['id']}"
    temp_root.mkdir(parents=True, exist_ok=True)
    conn = connect(temp_root / f"{session_id}.db")
    try:
        new_session(conn, session_id, persona.persona_id, title=None)
        if case["scenario"] == "memory":
            _seed_memory(conn, session_id, memory_bundle)
        core = PersonaSessionCore(persona, constraint_assets=constraint_assets)
        replies: list[str] = []
        turns_out: list[dict[str, Any]] = []
        recall_counts: list[int] = []
        repetition_traces: list[dict[str, Any]] = []
        l4_traces: list[dict[str, Any]] = []
        for turn in case["turns"]:
            user_message = str(turn["user"])
            history = recent_messages(conn, session_id, limit=20)
            result = core.assemble_reply(
                backend,
                conn,
                user_message=user_message,
                history=history,
                memory_enabled=True,
                max_tokens=max_tokens,
                expression_config=expression_config,
            )
            append_message(conn, session_id, "user", user_message, {"case_id": case["id"]})
            append_message(
                conn,
                session_id,
                "assistant",
                result.reply,
                {
                    "case_id": case["id"],
                    "cross_turn_repetition_trace": asdict(result.repetition_trace),
                },
            )
            replies.append(result.reply)
            turns_out.append({"id": turn.get("id"), "user": user_message})
            recall_counts.append(len(result.memory_recalls))
            repetition_traces.append(asdict(result.repetition_trace))
            l4_traces.append(asdict(result.l4_trace))
        return {
            "id": case["id"],
            "scenario": case["scenario"],
            "group": case.get("group", case["id"]),
            "focus": case.get("focus", []),
            "turns": turns_out,
            "replies": replies,
            "recall_counts": recall_counts,
            "repetition_traces": repetition_traces,
            "l4_traces": l4_traces,
        }
    finally:
        conn.close()


def _checkpoint_path(args: argparse.Namespace, arm: str, seed: int) -> Path:
    return args.checkpoint_dir / f"w3_p2_2_arm_{arm.lower()}_seed{seed}.json"


def _run_arm_seed(
    args: argparse.Namespace,
    *,
    arm: str,
    seed: int,
    cases_fixture: dict[str, Any],
    validation_fixture: dict[str, Any],
    constraint_assets: Any,
) -> dict[str, Any]:
    """摘要：运行一个 arm×seed 的原始 gate 矩阵与独立验证窗。"""

    checkpoint = _checkpoint_path(args, arm, seed)
    if args.resume and checkpoint.is_file():
        print(f"[P2-2] arm={arm} seed={seed} resume {checkpoint}", flush=True)
        return json.loads(checkpoint.read_text(encoding="utf-8"))
    print(f"[P2-2] arm={arm} seed={seed} start", flush=True)
    persona = _load_persona(args.persona)
    backend = _build_backend(args, seed=seed)
    config = _arm_config(arm)
    memory_bundle = list(cases_fixture.get("memory_bundle", []))
    with tempfile.TemporaryDirectory(prefix=f"oc-w3-p2-2-{arm}-{seed}-") as temp_dir:
        temp_root = Path(temp_dir)
        cases = [
            _run_case(
                case=case,
                memory_bundle=memory_bundle,
                persona=persona,
                backend=backend,
                constraint_assets=constraint_assets,
                temp_root=temp_root / "gate",
                max_tokens=args.max_tokens,
                expression_config=config,
            )
            for case in cases_fixture["cases"]
        ]
        validation_cases = [
            _run_case(
                case=case,
                memory_bundle=memory_bundle,
                persona=persona,
                backend=backend,
                constraint_assets=constraint_assets,
                temp_root=temp_root / "validation",
                max_tokens=args.max_tokens,
                expression_config=config,
            )
            for case in validation_fixture["cases"]
        ]
    payload = {
        "cases": cases,
        "metrics": calculate_metrics({"cases": cases}),
        "validation_cases": validation_cases,
        "validation_metrics": calculate_metrics({"cases": validation_cases}),
    }
    _write_json(checkpoint, payload)
    del backend
    gc.collect()
    print(f"[P2-2] arm={arm} seed={seed} done", flush=True)
    return payload


def _trace_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """摘要：按 first.action 聚合真实触发样本与高分未触发校准缺口。"""

    triggered: list[dict[str, Any]] = []
    calibration_gaps: list[dict[str, Any]] = []
    for arm, arm_payload in payload["arms"].items():
        for seed_name, run in arm_payload["case_runs"].items():
            for source, cases in (
                ("gate", run["cases"]),
                ("validation", run["validation_cases"]),
            ):
                for case in cases:
                    traces = case["repetition_traces"]
                    l4_traces = case["l4_traces"]
                    replies = case["replies"]
                    for turn_index, trace in enumerate(traces):
                        first = trace.get("first") or {}
                        if first.get("action") == "retry":
                            retry = trace.get("retry") or {}
                            triggered.append(
                                {
                                    "arm": arm,
                                    "seed": seed_name,
                                    "source": source,
                                    "case_id": case["id"],
                                    "turn_index": turn_index,
                                    "first_score": first.get("score"),
                                    "retry_action": retry.get("action"),
                                    "retry_score": retry.get("score"),
                                    "retry_below_0_02": (
                                        isinstance(retry.get("score"), int | float)
                                        and retry["score"] < LOCAL_RETRY_GATE
                                    ),
                                    "guard_outcome": trace.get("outcome"),
                                    "guard_retry_taken": trace.get("retry_taken"),
                                    "l4_outcome": l4_traces[turn_index].get("outcome"),
                                }
                            )
                        if turn_index == 0:
                            continue
                        shipped_score = cross_turn_repetition_score(
                            replies[turn_index - 1],
                            replies[turn_index],
                        )
                        if (
                            shipped_score > CROSS_TURN_REPETITION_RUNTIME_THRESHOLD
                            and first.get("action") != "retry"
                        ):
                            calibration_gaps.append(
                                {
                                    "arm": arm,
                                    "seed": seed_name,
                                    "source": source,
                                    "case_id": case["id"],
                                    "turn_index": turn_index,
                                    "shipped_score": shipped_score,
                                    "first_action": first.get("action"),
                                    "first_reason": first.get("reason"),
                                }
                            )
    return triggered, calibration_gaps


def _acceptance(payload: dict[str, Any]) -> dict[str, Any]:
    """摘要：机械计算局部 retry 与 A/B 原始全局 gate 验收。"""

    arm_gates: dict[str, Any] = {}
    for arm, arm_payload in payload["arms"].items():
        seed_values = {
            seed_name: run["metrics"]["aggregate"]["cross_turn_4gram_jaccard_mean"]
            for seed_name, run in arm_payload["case_runs"].items()
        }
        aggregate = round(statistics.fmean(seed_values.values()), 6)
        arm_gates[arm] = {
            "seed_values": seed_values,
            "aggregate_mean": aggregate,
            "threshold": GLOBAL_GATE,
            "passed": aggregate <= GLOBAL_GATE,
        }
    triggered, calibration_gaps = _trace_rows(payload)
    local_failures = [
        row
        for row in triggered
        if row["retry_action"] != "direct" or not row["retry_below_0_02"]
    ]
    return {
        "triggered_count": len(triggered),
        "local_retry_passed": not local_failures,
        "local_failures": local_failures,
        "arm_gates": arm_gates,
        "global_gate_passed": all(item["passed"] for item in arm_gates.values()),
        "calibration_gap_count": len(calibration_gaps),
        "calibration_gaps_require_review": bool(calibration_gaps),
        "mechanical_status": (
            "failed"
            if local_failures or not all(item["passed"] for item in arm_gates.values())
            else "needs_calibration_review"
            if calibration_gaps
            else "passed_pending_blind_review"
        ),
    }


def run_retest(args: argparse.Namespace) -> dict[str, Any]:
    """摘要：执行 A/B 三 seed 复测并返回完整矩阵。"""

    cases_fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    validation_fixture = json.loads(args.validation_cases.read_text(encoding="utf-8"))
    persona = _load_persona(args.persona)
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    if not args.skip_memory_check:
        backend = _build_backend(args, seed=args.case_seeds[0])
        _assert_memory_injection_live(
            PersonaSessionCore(persona, constraint_assets=assets),
            backend,
            list(cases_fixture.get("memory_bundle", [])),
        )
        del backend
        gc.collect()
    arms: dict[str, Any] = {}
    for arm in args.arms:
        case_runs = {
            f"seed{seed}": _run_arm_seed(
                args,
                arm=arm,
                seed=seed,
                cases_fixture=cases_fixture,
                validation_fixture=validation_fixture,
                constraint_assets=assets,
            )
            for seed in args.case_seeds
        }
        arms[arm] = {
            "config": asdict(_arm_config(arm)),
            "case_runs": case_runs,
            "case_metric_distribution": _metric_distribution(case_runs),
        }
    payload = {
        "meta": {
            "version": "w3-p2-2-retest-v1",
            "commit": _git_commit(),
            "model": args.backend if args.backend == "echo" else str(args.model),
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "case_seeds": list(args.case_seeds),
            "arms": list(args.arms),
            "persona": str(args.persona),
            "guard_enabled": True,
            "runtime_threshold": CROSS_TURN_REPETITION_RUNTIME_THRESHOLD,
            "global_gate": GLOBAL_GATE,
            "local_retry_gate": LOCAL_RETRY_GATE,
            "baseline_in_gate": False,
            "validation_cases_in_gate": False,
        },
        "arms": arms,
    }
    payload["acceptance"] = _acceptance(payload)
    return payload


def main() -> int:
    """摘要：运行复测并写出矩阵及触发样本清单。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--validation-cases", type=Path, default=DEFAULT_VALIDATION_CASES)
    parser.add_argument("--persona", type=Path, default=DEFAULT_PERSONA)
    parser.add_argument("--backend", choices=("echo", "llama"), default="echo")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trigger-output", type=Path, default=DEFAULT_TRIGGER_OUTPUT)
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--n-ctx", type=int, default=2048)
    parser.add_argument("--n-gpu-layers", type=int, default=0)
    parser.add_argument("--skip-health-check", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--case-seeds", type=_comma_ints, default=CASE_SEEDS)
    parser.add_argument("--arms", type=lambda value: tuple(value.upper().split(",")), default=("A", "B"))
    parser.add_argument("--skip-memory-check", action="store_true")
    args = parser.parse_args()
    with _exclusive_run_lock(args.lock_file):
        payload = run_retest(args)
        _write_json(args.output, payload)
        triggered, calibration_gaps = _trace_rows(payload)
        trigger_payload = {
            "meta": {
                "version": "w3-p2-2-trigger-samples-v1",
                "source": str(args.output),
                "source_sha256": _sha256(args.output),
                "selection": "repetition_trace.first.action == retry",
                "l4_joint_read_required": True,
            },
            "acceptance": payload["acceptance"],
            "triggered_samples": triggered,
            "calibration_gaps": calibration_gaps,
        }
        _write_json(args.trigger_output, trigger_payload)
    print(args.output)
    print(args.trigger_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
