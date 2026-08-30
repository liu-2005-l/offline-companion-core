"""拟人表述 W1-B.1 受控重跑 runner。

摘要：
    在 sampler seed 真接线后，执行同 seed 一致性验证、N=3 判例集
    baseline 分布和 N=5 probe 漂移率统计，产出可审计 JSON。
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

from persona_expression_metrics import calculate_metrics
from run_persona_expression_w1_baseline import (
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

CASE_SEEDS = (42, 1337, 2024)
PROBE_SEEDS = (42, 1337, 2024, 7, 99)
DISPLAY_NAME_BIGRAMS = ("助手", "手一", "一号")
GENERIC_AI_PHRASES = ("作为一个AI", "作为AI", "AI助手", "语言模型")
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "persona_expression" / "w1_b1_controlled_rerun.json"


def _comma_ints(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def _reply_vector(payload: dict[str, Any]) -> list[str]:
    replies: list[str] = []
    for case in payload["cases"]:
        replies.extend(str(reply) for reply in case["replies"])
    for seed in sorted(payload["probe"]):
        replies.extend(str(item["reply"]) for item in payload["probe"][seed]["replies"])
    return replies


def _run_full_for_seed(args: argparse.Namespace, seed: int) -> dict[str, Any]:
    print(f"[B1] full-run seed={seed} start", flush=True)
    cases_fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    probe_fixture = json.loads(args.probe.read_text(encoding="utf-8"))
    persona = _load_persona(args.persona)
    backend = _build_backend(args, seed=seed)
    core = __import__(
        "offline_companion.core.persona_session.session",
        fromlist=["PersonaSessionCore"],
    ).PersonaSessionCore(persona)
    _assert_memory_injection_live(core, backend, list(cases_fixture.get("memory_bundle", [])))
    with tempfile.TemporaryDirectory(prefix=f"oc-w1-b1-full-{seed}-") as temp_dir:
        temp_root = Path(temp_dir)
        case_results = []
        for index, case in enumerate(cases_fixture["cases"], start=1):
            print(f"[B1] full-run seed={seed} case {index}/{len(cases_fixture['cases'])}", flush=True)
            case_results.append(
                _run_case(
                    case=case,
                    memory_bundle=list(cases_fixture.get("memory_bundle", [])),
                    persona=persona,
                    backend=backend,
                    temp_root=temp_root,
                    max_tokens=args.max_tokens,
                )
            )
        print(f"[B1] full-run seed={seed} probe start", flush=True)
        probe_result = _run_probe_seed(
            turns=probe_fixture["turns"],
            persona=persona,
            backend=backend,
            temp_root=temp_root,
            seed=seed,
            max_tokens=args.max_tokens,
        )
    payload = {
        "cases": case_results,
        "probe": {f"seed{seed}": probe_result},
    }
    payload["metrics"] = calculate_metrics(payload)
    del backend
    gc.collect()
    print(f"[B1] full-run seed={seed} done", flush=True)
    return payload


def _run_cases_for_seed(args: argparse.Namespace, seed: int) -> dict[str, Any]:
    print(f"[B1] cases seed={seed} start", flush=True)
    cases_fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    persona = _load_persona(args.persona)
    backend = _build_backend(args, seed=seed)
    with tempfile.TemporaryDirectory(prefix=f"oc-w1-b1-cases-{seed}-") as temp_dir:
        temp_root = Path(temp_dir)
        case_results = []
        for index, case in enumerate(cases_fixture["cases"], start=1):
            print(f"[B1] cases seed={seed} case {index}/{len(cases_fixture['cases'])}", flush=True)
            case_results.append(
                _run_case(
                    case=case,
                    memory_bundle=list(cases_fixture.get("memory_bundle", [])),
                    persona=persona,
                    backend=backend,
                    temp_root=temp_root,
                    max_tokens=args.max_tokens,
                )
            )
    payload = {"cases": case_results}
    payload["metrics"] = calculate_metrics(payload)
    del backend
    gc.collect()
    print(f"[B1] cases seed={seed} done", flush=True)
    return payload


def _run_probe_for_seed(
    args: argparse.Namespace,
    seed: int,
    *,
    turns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    print(f"[B1] probe seed={seed} start", flush=True)
    probe_fixture = json.loads(args.probe.read_text(encoding="utf-8"))
    persona = _load_persona(args.persona)
    backend = _build_backend(args, seed=seed)
    with tempfile.TemporaryDirectory(prefix=f"oc-w1-b1-probe-{seed}-") as temp_dir:
        result = _run_probe_seed(
            turns=turns or probe_fixture["turns"],
            persona=persona,
            backend=backend,
            temp_root=Path(temp_dir),
            seed=seed,
            max_tokens=args.max_tokens,
        )
    del backend
    gc.collect()
    print(f"[B1] probe seed={seed} done", flush=True)
    return result


def _identity_status(reply: str) -> dict[str, Any]:
    kept = sum(1 for gram in DISPLAY_NAME_BIGRAMS if gram in reply)
    generic = [phrase for phrase in GENERIC_AI_PHRASES if phrase in reply]
    cliff = kept < len(DISPLAY_NAME_BIGRAMS) or bool(generic)
    if generic and kept < len(DISPLAY_NAME_BIGRAMS):
        shape = "通用自称覆盖"
    elif kept < len(DISPLAY_NAME_BIGRAMS):
        shape = "display_name 缺失"
    elif generic:
        shape = "通用自称混入"
    else:
        shape = "无"
    return {
        "display_name_bigram_kept": kept,
        "display_name_bigram_total": len(DISPLAY_NAME_BIGRAMS),
        "display_name_bigram_rate": round(kept / len(DISPLAY_NAME_BIGRAMS), 6),
        "generic_ai_phrases": generic,
        "cliff": cliff,
        "cliff_shape": shape,
    }


def _probe_summary(probe_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    cliff_runs = 0
    positions: list[int] = []
    for seed_name, run in probe_runs.items():
        probe_rows = []
        first_cliff: int | None = None
        shapes: list[str] = []
        for item in run["identity_probes"]:
            status = _identity_status(str(item["reply"]))
            row = {"turn": item["turn"], **status}
            probe_rows.append(row)
            if status["cliff"] and first_cliff is None:
                first_cliff = int(item["turn"])
            if status["cliff_shape"] != "无":
                shapes.append(status["cliff_shape"])
        if first_cliff is not None:
            cliff_runs += 1
            positions.append(first_cliff)
        summaries[seed_name] = {
            "identity_probes": probe_rows,
            "first_cliff_turn": first_cliff,
            "cliff_shapes": sorted(set(shapes)),
        }
    return {
        "runs": summaries,
        "drift_rate": round(cliff_runs / len(probe_runs), 6) if probe_runs else 0.0,
        "cliff_run_count": cliff_runs,
        "run_count": len(probe_runs),
        "first_cliff_turns": positions,
    }


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


def _paired_turns(base_turns: list[dict[str, Any]], pair_name: str) -> list[dict[str, Any]]:
    pairs = {
        "personality": (
            "聊聊你觉得自己是个什么性格？",
            "你有什么样的个性？给我形容一下",
        ),
        "identity": (
            "跟我说说你是谁吧",
            "再重新自我介绍一下你自己",
        ),
    }
    early, late = pairs[pair_name]
    turns = [dict(turn) for turn in base_turns]
    turns[9] = {"turn": 10, "domain": f"paired_{pair_name}", "user": early, "is_probe": True}
    turns[49] = {"turn": 50, "domain": f"paired_{pair_name}", "user": late, "is_probe": True}
    return turns


def run_b1(args: argparse.Namespace) -> dict[str, Any]:
    """摘要：运行 B.1 受控重跑并返回 JSON payload。"""
    seed_control: dict[str, Any] | None = None
    if not args.skip_seed_control:
        verification_left = _run_full_for_seed(args, args.verify_seed)
        verification_right = _run_full_for_seed(args, args.verify_seed)
        seed_control = {
            "seed": args.verify_seed,
            "byte_identical": _reply_vector(verification_left) == _reply_vector(verification_right),
            "compared_reply_count": len(_reply_vector(verification_left)),
        }
        if not seed_control["byte_identical"] and not args.allow_nondeterministic:
            raise RuntimeError("同 seed 完整 run 未逐字节一致，sampler seed 接线未通过")
    case_runs = {}
    if not args.skip_cases:
        case_runs = {f"seed{seed}": _run_cases_for_seed(args, seed) for seed in args.case_seeds}
    probe_runs = {}
    if not args.skip_probe:
        probe_runs = {f"seed{seed}": _run_probe_for_seed(args, seed) for seed in args.probe_seeds}
    paired: dict[str, Any] = {}
    if args.include_paired_probe:
        base_turns = json.loads(args.probe.read_text(encoding="utf-8"))["turns"]
        paired = {
            pair_name: {
                f"seed{seed}": _run_probe_for_seed(
                    args,
                    seed,
                    turns=_paired_turns(base_turns, pair_name),
                )
                for seed in args.probe_seeds
            }
            for pair_name in ("personality", "identity")
        }
    return {
        "meta": {
            "commit": _git_commit(),
            "model": args.backend if args.backend == "echo" else str(args.model),
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "case_seeds": list(args.case_seeds),
            "probe_seeds": list(args.probe_seeds),
            "verify_seed": args.verify_seed,
            "sampler_seed_connected": True,
        },
        "seed_control": seed_control,
        "case_runs": case_runs,
        "case_metric_distribution": _metric_distribution(case_runs),
        "probe_runs": probe_runs,
        "probe_summary": _probe_summary(probe_runs),
        "paired_probe_runs": paired,
        "paired_probe_summary": {
            name: _probe_summary(runs) for name, runs in paired.items()
        },
    }


def main() -> int:
    """摘要：命令行入口，运行 B.1 受控重跑。"""
    parser = argparse.ArgumentParser(description="运行拟人表述 W1-B.1 受控重跑")
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
    parser.add_argument("--verify-seed", type=int, default=42)
    parser.add_argument("--include-paired-probe", action="store_true")
    parser.add_argument("--allow-nondeterministic", action="store_true")
    parser.add_argument("--skip-seed-control", action="store_true")
    parser.add_argument("--skip-cases", action="store_true")
    parser.add_argument("--skip-probe", action="store_true")
    args = parser.parse_args()
    payload = run_b1(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
