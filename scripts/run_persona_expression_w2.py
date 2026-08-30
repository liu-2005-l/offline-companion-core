"""拟人表述 W2 三臂测量 runner。

摘要：
    复用 W1 判例与 probe fixture，按 A/B/C 三臂运行判例集与 50 轮
    probe，输出六指标、身份断崖两层统计与每轮防线 trace。
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from offline_companion.core.persona_session.expression import (  # noqa: E402
    PersonaExpressionConfig,
    detect_identity_cliff,
)
from offline_companion.core.persona_session.persona_loader import (  # noqa: E402
    resolved_companion_display_name,
)
from persona_expression_metrics import calculate_metrics  # noqa: E402
from run_persona_expression_w1_b1 import (  # noqa: E402
    CASE_SEEDS,
    PROBE_SEEDS,
    _comma_ints,
    _identity_status,
)
from run_persona_expression_w1_baseline import (  # noqa: E402
    DEFAULT_CASES,
    DEFAULT_PERSONA,
    DEFAULT_PROBE,
    _assert_memory_injection_live,
    _build_backend,
    _git_commit,
    _load_persona,
    _run_case,
    _run_probe_seed,
)

DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "persona_expression" / "w2_three_arm_matrix.json"


def _arm_config(arm: str) -> PersonaExpressionConfig:
    if arm == "A":
        return PersonaExpressionConfig(style_examples_enabled=True)
    if arm == "B":
        return PersonaExpressionConfig(
            style_examples_enabled=True,
            identity_near_prompt_enabled=True,
        )
    if arm == "C":
        return PersonaExpressionConfig(
            style_examples_enabled=True,
            identity_near_prompt_enabled=True,
            identity_exit_guard_enabled=True,
        )
    raise ValueError(f"未知 W2 arm: {arm}")


def _metric_distribution(case_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    names = set()
    for run in case_runs.values():
        names.update(run["metrics"]["aggregate"].keys())
    out: dict[str, Any] = {}
    for name in sorted(names):
        values = [
            run["metrics"]["aggregate"][name]
            for run in case_runs.values()
            if isinstance(run["metrics"]["aggregate"].get(name), int | float)
        ]
        if values:
            out[name] = {
                "values": values,
                "mean": round(statistics.fmean(values), 6),
                "min": min(values),
                "max": max(values),
                "range": round(max(values) - min(values), 6),
            }
    return out


def _case_trace_summary(case_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total_replies = 0
    for run in case_runs.values():
        for case in run["cases"]:
            total_replies += len(case.get("replies", []))
    return {"reply_count": total_replies}


def _probe_summary(probe_runs: dict[str, dict[str, Any]], display_name: str) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    first_cliff_runs = 0
    shipped_cliff_runs = 0
    first_positions: list[int] = []
    shipped_positions: list[int] = []
    output_sources: dict[str, int] = {}
    retry_saved = 0
    fallback_saved = 0
    for seed_name, run in probe_runs.items():
        traces_by_turn = {
            int(item["turn"]): item for item in run.get("expression_traces", [])
        }
        rows = []
        first_cliff_turn: int | None = None
        shipped_cliff_turn: int | None = None
        for item in run["identity_probes"]:
            turn = int(item["turn"])
            shipped_status = _identity_status(str(item["reply"]))
            trace = traces_by_turn.get(turn, {})
            detector_observed_cliff = detect_identity_cliff(str(item["reply"]), display_name)
            first_cliff = bool(trace.get("first_generation_cliff", detector_observed_cliff))
            if not trace.get("retry_taken") and not trace.get("first_generation_cliff"):
                first_cliff = detector_observed_cliff
            shipped_cliff = detect_identity_cliff(str(item["reply"]), display_name)
            output_source = str(trace.get("output_source") or "direct")
            output_sources[output_source] = output_sources.get(output_source, 0) + 1
            if first_cliff and first_cliff_turn is None:
                first_cliff_turn = turn
            if shipped_cliff and shipped_cliff_turn is None:
                shipped_cliff_turn = turn
            if first_cliff and not shipped_cliff and output_source == "retry":
                retry_saved += 1
            if first_cliff and not shipped_cliff and output_source == "fallback":
                fallback_saved += 1
            rows.append(
                {
                    "turn": turn,
                    "first_generation_cliff": first_cliff,
                    "detector_observed_cliff": detector_observed_cliff,
                    "shipped_cliff": shipped_cliff,
                    "output_source": output_source,
                    "shipped_identity_status": shipped_status,
                    "trace": trace,
                }
            )
        if first_cliff_turn is not None:
            first_cliff_runs += 1
            first_positions.append(first_cliff_turn)
        if shipped_cliff_turn is not None:
            shipped_cliff_runs += 1
            shipped_positions.append(shipped_cliff_turn)
        summaries[seed_name] = {
            "identity_probes": rows,
            "first_cliff_turn": first_cliff_turn,
            "shipped_cliff_turn": shipped_cliff_turn,
        }
    run_count = len(probe_runs)
    return {
        "runs": summaries,
        "run_count": run_count,
        "first_generation_cliff_run_count": first_cliff_runs,
        "first_generation_cliff_rate": round(first_cliff_runs / run_count, 6) if run_count else 0.0,
        "first_generation_cliff_turns": first_positions,
        "shipped_cliff_run_count": shipped_cliff_runs,
        "shipped_cliff_rate": round(shipped_cliff_runs / run_count, 6) if run_count else 0.0,
        "shipped_cliff_turns": shipped_positions,
        "output_sources": output_sources,
        "retry_saved_probe_count": retry_saved,
        "fallback_saved_probe_count": fallback_saved,
    }


def _run_cases_for_arm_seed(args: argparse.Namespace, arm: str, seed: int) -> dict[str, Any]:
    print(f"[W2] arm={arm} cases seed={seed} start", flush=True)
    cases_fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    persona = _load_persona(args.persona)
    backend = _build_backend(args, seed=seed)
    config = _arm_config(arm)
    with tempfile.TemporaryDirectory(prefix=f"oc-w2-{arm}-cases-{seed}-") as temp_dir:
        temp_root = Path(temp_dir)
        case_results = [
            _run_case(
                case=case,
                memory_bundle=list(cases_fixture.get("memory_bundle", [])),
                persona=persona,
                backend=backend,
                temp_root=temp_root,
                max_tokens=args.max_tokens,
                expression_config=config,
            )
            for case in cases_fixture["cases"]
        ]
    payload = {"cases": case_results}
    payload["metrics"] = calculate_metrics(payload)
    del backend
    gc.collect()
    print(f"[W2] arm={arm} cases seed={seed} done", flush=True)
    return payload


def _run_probe_for_arm_seed(args: argparse.Namespace, arm: str, seed: int) -> dict[str, Any]:
    print(f"[W2] arm={arm} probe seed={seed} start", flush=True)
    probe_fixture = json.loads(args.probe.read_text(encoding="utf-8"))
    persona = _load_persona(args.persona)
    backend = _build_backend(args, seed=seed)
    config = _arm_config(arm)
    with tempfile.TemporaryDirectory(prefix=f"oc-w2-{arm}-probe-{seed}-") as temp_dir:
        result = _run_probe_seed(
            turns=probe_fixture["turns"],
            persona=persona,
            backend=backend,
            temp_root=Path(temp_dir),
            seed=seed,
            max_tokens=args.max_tokens,
            expression_config=config,
        )
    del backend
    gc.collect()
    print(f"[W2] arm={arm} probe seed={seed} done", flush=True)
    return result


def _assert_style_examples_live(args: argparse.Namespace) -> None:
    persona = _load_persona(args.persona)
    backend = _build_backend(args, seed=args.case_seeds[0] if args.case_seeds else None)
    from offline_companion.core.persona_session.session import PersonaSessionCore
    from offline_companion.runtime.storage_index.engine import connect, new_session

    with tempfile.TemporaryDirectory(prefix="oc-w2-style-check-") as temp_dir:
        conn = connect(Path(temp_dir) / "style-check.db")
        try:
            session_id = "w2-style-check"
            new_session(conn, session_id, persona.persona_id, title=None)
            result = PersonaSessionCore(persona).assemble_reply(
                backend,
                conn,
                user_message="随便聊聊",
                history=[],
                memory_enabled=False,
                max_tokens=64,
                expression_config=_arm_config("A"),
            )
            if not result.expression_trace.style_block_injected:
                raise RuntimeError("W2 臂 A style block 未注入，拒绝开跑矩阵")
        finally:
            conn.close()


def run_w2(args: argparse.Namespace) -> dict[str, Any]:
    """摘要：运行 W2 三臂矩阵并返回可落档 payload。"""
    persona = _load_persona(args.persona)
    display_name = resolved_companion_display_name(persona)
    cases_fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    if not args.skip_style_check:
        _assert_style_examples_live(args)
    if not args.skip_memory_check:
        backend = _build_backend(args, seed=args.case_seeds[0] if args.case_seeds else None)
        from offline_companion.core.persona_session.session import PersonaSessionCore

        _assert_memory_injection_live(
            PersonaSessionCore(persona),
            backend,
            list(cases_fixture.get("memory_bundle", [])),
        )
    arms: dict[str, Any] = {}
    for arm in args.arms:
        case_runs = {}
        if not args.skip_cases:
            case_runs = {f"seed{seed}": _run_cases_for_arm_seed(args, arm, seed) for seed in args.case_seeds}
        probe_runs = {}
        if not args.skip_probe:
            probe_runs = {f"seed{seed}": _run_probe_for_arm_seed(args, arm, seed) for seed in args.probe_seeds}
        arms[arm] = {
            "config": _arm_config(arm).__dict__,
            "case_runs": case_runs,
            "case_metric_distribution": _metric_distribution(case_runs),
            "case_trace_summary": _case_trace_summary(case_runs),
            "probe_runs": probe_runs,
            "probe_summary": _probe_summary(probe_runs, display_name),
        }
    return {
        "meta": {
            "commit": _git_commit(),
            "model": args.backend if args.backend == "echo" else str(args.model),
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "case_seeds": list(args.case_seeds),
            "probe_seeds": list(args.probe_seeds),
            "arms": list(args.arms),
            "persona": str(args.persona),
            "display_name": display_name,
        },
        "arms": arms,
    }


def main() -> int:
    """摘要：命令行入口，运行 W2 三臂测量矩阵。"""
    parser = argparse.ArgumentParser(description="运行拟人表述 W2 三臂测量矩阵")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--persona", type=Path, default=DEFAULT_PERSONA)
    parser.add_argument("--backend", choices=("echo", "llama"), default="echo")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--n-ctx", type=int, default=2048)
    parser.add_argument("--n-gpu-layers", type=int, default=0)
    parser.add_argument("--skip-health-check", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--case-seeds", type=_comma_ints, default=CASE_SEEDS)
    parser.add_argument("--probe-seeds", type=_comma_ints, default=PROBE_SEEDS)
    parser.add_argument("--arms", type=lambda value: tuple(value.upper().split(",")), default=("A", "B", "C"))
    parser.add_argument("--skip-style-check", action="store_true")
    parser.add_argument("--skip-memory-check", action="store_true")
    parser.add_argument("--skip-cases", action="store_true")
    parser.add_argument("--skip-probe", action="store_true")
    args = parser.parse_args()
    payload = run_w2(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
