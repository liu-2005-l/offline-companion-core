"""执行本地 llama-server GBNF Booth 步骤生成实验（Batch C）。"""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from offline_companion.core.algorithm_tools import booth_multiply
from offline_companion.runtime.inference_backend.llama_server_backend import LlamaServerBackend


DEFAULT_TEMPERATURE = 0.7
DEFAULT_SEED = 20260824
BOUNDARY_LOW = 0.7
BOUNDARY_HIGH = 0.85
PROMPT_TEMPLATE = (
    "请严格按 Booth 乘法算法计算 {multiplicand} 乘 {multiplier}。"
    "只输出 JSON，不要解释。JSON 字段必须是 multiplicand、multiplier、recoding、"
    "partial_products、rounds、result。rounds 每项只包含 round、pair、"
    "accumulator_after_shift、multiplier_after_shift。"
)


@dataclass(frozen=True)
class BoothCase:
    """摘要：一条 Booth GBNF 实验输入。"""

    label: str
    multiplicand: int
    multiplier: int

    @property
    def prompt(self) -> str:
        """摘要：返回发送给模型的中文实验提示。"""
        return PROMPT_TEMPLATE.format(
            multiplicand=self.multiplicand,
            multiplier=self.multiplier,
        )


DISTRIBUTION_CASES = (
    BoothCase("small_7x3", 7, 3),
    BoothCase("small_3x7", 3, 7),
    BoothCase("small_5x8", 5, 8),
    BoothCase("square_6x6", 6, 6),
    BoothCase("single_bit_9x4", 9, 4),
    BoothCase("teen_12x11", 12, 11),
    BoothCase("teen_15x3", 15, 3),
    BoothCase("zero_left", 0, 9),
    BoothCase("zero_right", 10, 0),
    BoothCase("negative_left", -3, 7),
    BoothCase("negative_right", 7, -3),
    BoothCase("negative_both", -4, -5),
    BoothCase("power_boundary", 16, 7),
    BoothCase("wide_31x2", 31, 2),
    BoothCase("mid_13x9", 13, 9),
    BoothCase("mid_21x5", 21, 5),
    BoothCase("mid_24x12", 24, 12),
    BoothCase("large_77x88", 77, 88),
    BoothCase("large_123x45", 123, 45),
    BoothCase("carry_63x15", 63, 15),
)
REPEAT_CASE = BoothCase("repeat_7x3", 7, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch C Booth GBNF sampling")
    parser.add_argument("--url", default=os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--case-set", choices=("distribution", "repeat"), default="distribution")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--greedy-on-boundary", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--managed-sidecar", action="store_true")
    parser.add_argument("--model-path", default=os.environ.get("OC_GBNF_MODEL_PATH", "models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"))
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    args = parser.parse_args()

    cases = select_cases(args.case_set, args.samples)
    grammar = booth_steps_grammar()
    protocol = {
        "experiment": "booth_gbnf_plan_as_reasoning",
        "case_set": args.case_set,
        "samples": len(cases),
        "temperature": args.temperature,
        "seed": args.seed,
        "decision_metric": "full_success_rate",
        "diagnostic_metrics": ("result_rate", "recoding_rate", "partial_products_rate", "rounds_rate"),
        "grammar": grammar,
        "cases": [case.__dict__ | {"prompt": case.prompt} for case in cases],
    }
    if args.dry_run:
        _emit(protocol, args.output)
        return 0

    backend: LlamaServerBackend | None = None
    url = args.url
    if args.managed_sidecar:
        backend = LlamaServerBackend(
            args.model_path,
            n_ctx=4096,
            n_gpu_layers=0,
            startup_timeout=args.startup_timeout,
        )
        health = backend.health_check()
        if not health.ok:
            report = _blocked_report(
                protocol,
                {"status": "blocked", "error": health.message, "backend": health.backend},
            )
            _emit(report, args.output)
            return 2
        url = backend._base_url

    try:
        if not args.skip_preflight:
            preflight = _preflight(url)
            if preflight["status"] != "completed":
                report = _blocked_report(protocol, preflight)
                _emit(report, args.output)
                return 2
        else:
            preflight = {"status": "skipped"}

        results = [
            sample_case(
                url,
                case,
                grammar,
                temperature=args.temperature,
                seed=args.seed + index,
            )
            for index, case in enumerate(cases)
        ]
        report = build_report(protocol, preflight, results)
        if args.greedy_on_boundary and report["status"] == "boundary":
            greedy_case = cases[0]
            greedy_result = sample_case(
                url,
                greedy_case,
                grammar,
                temperature=0.0,
                seed=args.seed,
            )
            report["greedy_probe"] = {
                "temperature": 0.0,
                "case": greedy_case.__dict__ | {"prompt": greedy_case.prompt},
                "result": greedy_result,
            }
        _emit(report, args.output)
        return 0 if report["completed"] == report["samples"] else 2
    finally:
        if backend is not None:
            backend.stop()


def select_cases(case_set: str, samples: int) -> tuple[BoothCase, ...]:
    """摘要：按实验口径选择样本集。"""
    if samples <= 0:
        raise ValueError("samples must be positive")
    if case_set == "repeat":
        return tuple(REPEAT_CASE for _ in range(samples))
    repeated = list(DISTRIBUTION_CASES)
    while len(repeated) < samples:
        repeated.extend(DISTRIBUTION_CASES)
    return tuple(repeated[:samples])


def booth_steps_grammar() -> str:
    """摘要：返回 Booth 步骤 JSON 的 GBNF 文法。"""
    return r'''
root ::= "{" ws "\"multiplicand\":" ws integer "," ws "\"multiplier\":" ws integer "," ws "\"recoding\":" ws string "," ws "\"partial_products\":" ws integer-array "," ws "\"rounds\":" ws round-array "," ws "\"result\":" ws integer ws "}"
round-array ::= "[" ws round (ws "," ws round)* ws "]"
round ::= "{" ws "\"round\":" ws integer "," ws "\"pair\":" ws pair "," ws "\"accumulator_after_shift\":" ws integer "," ws "\"multiplier_after_shift\":" ws integer ws "}"
integer-array ::= "[" ws integer (ws "," ws integer)* ws "]" | "[]"
pair ::= "\"00\"" | "\"01\"" | "\"10\"" | "\"11\""
string ::= "\"" chars "\""
chars ::= [^"\\]*
integer ::= "-"? [0-9]+
ws ::= [ \t\n]*
'''.strip()


def sample_case(
    url: str,
    case: BoothCase,
    grammar: str,
    *,
    temperature: float,
    seed: int,
) -> dict[str, Any]:
    """摘要：执行单条 sidecar 采样并返回校验结果。"""
    payload = {
        "model": "local",
        "messages": [{"role": "user", "content": case.prompt}],
        "max_tokens": 512,
        "stream": False,
        "temperature": temperature,
        "seed": seed,
        "grammar": grammar,
    }
    try:
        content = _post_chat_completion(url, payload, timeout=60)
    except (OSError, URLError, KeyError, TypeError, ValueError) as exc:
        return {
            "case": case.__dict__ | {"prompt": case.prompt},
            "status": "blocked",
            "temperature": temperature,
            "seed": seed,
            "error": str(exc),
            "validation": _empty_validation(),
        }
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return {
            "case": case.__dict__ | {"prompt": case.prompt},
            "status": "completed",
            "temperature": temperature,
            "seed": seed,
            "content": content,
            "error": str(exc),
            "validation": _empty_validation(),
        }
    validation = validate_booth_output(case, parsed)
    return {
        "case": case.__dict__ | {"prompt": case.prompt},
        "status": "completed",
        "temperature": temperature,
        "seed": seed,
        "content": content,
        "output": parsed,
        "validation": validation,
    }


def validate_booth_output(case: BoothCase, output: Any) -> dict[str, bool]:
    """摘要：对模型 Booth JSON 做用户视角全对校验与定位指标。"""
    if not isinstance(output, dict):
        return _empty_validation()
    expected = booth_multiply(case.multiplicand, case.multiplier)
    rounds = output.get("rounds")
    expected_rounds = expected["rounds"]
    input_ok = (
        output.get("multiplicand") == case.multiplicand
        and output.get("multiplier") == case.multiplier
    )
    result_ok = output.get("result") == expected["result"]
    recoding_ok = output.get("recoding") == expected["recoding"]
    partial_products_ok = output.get("partial_products") == expected["partial_products"]
    rounds_ok = isinstance(rounds, list) and [
        {
            "round": item.get("round") if isinstance(item, dict) else None,
            "pair": item.get("pair") if isinstance(item, dict) else None,
            "accumulator_after_shift": item.get("accumulator_after_shift") if isinstance(item, dict) else None,
            "multiplier_after_shift": item.get("multiplier_after_shift") if isinstance(item, dict) else None,
        }
        for item in rounds
    ] == [
        {
            "round": item["round"],
            "pair": item["pair"],
            "accumulator_after_shift": item["accumulator_after_shift"],
            "multiplier_after_shift": item["multiplier_after_shift"],
        }
        for item in expected_rounds
    ]
    full_success = all(
        (
            input_ok,
            result_ok,
            recoding_ok,
            partial_products_ok,
            rounds_ok,
        )
    )
    return {
        "input": input_ok,
        "result": result_ok,
        "recoding": recoding_ok,
        "partial_products": partial_products_ok,
        "rounds": rounds_ok,
        "full_success": full_success,
    }


def build_report(
    protocol: dict[str, Any],
    preflight: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """摘要：汇总实验结果并给出三分支判定。"""
    completed = [item for item in results if item["status"] == "completed"]
    metrics = _metrics(results)
    full_success_rate = metrics["full_success_rate"]
    if len(completed) < len(results):
        status = "blocked"
        decision = "blocked：sidecar 或 grammar 能力未完成，不能判定 plan-as-reasoning"
    elif full_success_rate >= 0.8:
        status = "candidate"
        decision = "立项候选：结构约束下 Booth 全步骤正确率达到阈值"
    elif full_success_rate <= 0.5:
        status = "closed"
        decision = "关闭入档：结构约束下 Booth 全步骤正确率低于阈值"
    else:
        status = "middle"
        decision = "中间带：需要 few-shot 复测一轮再判"
    if BOUNDARY_LOW <= full_success_rate <= BOUNDARY_HIGH and len(completed) == len(results):
        status = "boundary"
        decision = "边界带：追加 temperature=0 贪心探针并分列入档"
    return {
        **{key: value for key, value in protocol.items() if key != "grammar"},
        "preflight": preflight,
        "status": status,
        "decision": decision,
        "completed": len(completed),
        "metrics": metrics,
        "results": results,
    }


def _metrics(results: list[dict[str, Any]]) -> dict[str, float]:
    total = len(results) or 1
    counters = {
        "input": 0,
        "result": 0,
        "recoding": 0,
        "partial_products": 0,
        "rounds": 0,
        "full_success": 0,
    }
    for item in results:
        validation = item.get("validation") if isinstance(item, dict) else None
        if not isinstance(validation, dict):
            continue
        for key in counters:
            counters[key] += int(bool(validation.get(key)))
    return {f"{key}_rate": value / total for key, value in counters.items()}


def _preflight(url: str) -> dict[str, Any]:
    payload = {
        "model": "local",
        "messages": [{"role": "user", "content": "只输出 OK"}],
        "max_tokens": 8,
        "stream": False,
        "temperature": 0.0,
        "grammar": 'root ::= "OK"',
    }
    try:
        content = _post_chat_completion(url, payload, timeout=20)
        return {"status": "completed", "content": content, "grammar_enforced": content == "OK"}
    except (OSError, URLError, KeyError, TypeError, ValueError) as exc:
        return {"status": "blocked", "error": str(exc)}


def _post_chat_completion(url: str, payload: dict[str, Any], *, timeout: int) -> str:
    request = Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    return str(body["choices"][0]["message"]["content"]).strip()


def _blocked_report(protocol: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in protocol.items() if key != "grammar"},
        "preflight": preflight,
        "status": "blocked",
        "decision": "blocked：pre-flight 未通过，未进入 Booth 采样",
        "completed": 0,
        "metrics": _metrics([]),
        "results": [],
    }


def _empty_validation() -> dict[str, bool]:
    return {
        "input": False,
        "result": False,
        "recoding": False,
        "partial_products": False,
        "rounds": False,
        "full_success": False,
    }


def _emit(report: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    raise SystemExit(main())
