"""人格约束 P1 E/A 维度拼接微型预实验。

摘要：
    按预注册 fixture 运行四个 E/A 组合、三种提示组装形态和固定 seeds，
    输出原始回复、方向分数、禁用标记与 P2 语料形态候选裁决数据。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from offline_companion.runtime.inference_backend.backend import create_llama_backend

DEFAULT_FIXTURE = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_ea_composition.json"
DEFAULT_MODEL = REPO_ROOT / "models" / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "persona_constraints" / "p1_ea_preexperiment.json"
PROFILE_LEVELS = (
    ("high", "high"),
    ("high", "low"),
    ("low", "high"),
    ("low", "low"),
)


class _EchoBackend:
    """摘要：返回固定回复的轻量 backend，供 runner 结构测试。"""

    def generate(
        self,
        *,
        system_prompt: str,
        history: list[Any],
        user_message: str,
        memory_block: str,
        max_tokens: int,
    ) -> str:
        return f"可以一起说说怎么处理？确实不容易。{user_message}"


def _dialogue_text(title: str, dialogue: list[dict[str, str]]) -> str:
    """摘要：把预注册微型对话转为稳定的提示块。"""
    lines = [title]
    for index, turn in enumerate(dialogue, start=1):
        lines.append(f"示例 {index} 用户：{turn['user']}")
        lines.append(f"示例 {index} 助手：{turn['assistant']}")
    return "\n".join(lines)


def build_system_prompt(fixture: dict[str, Any], shape: str, e_level: str, a_level: str) -> str:
    """摘要：按形态组装单一 E/A 组合的系统提示。"""
    units = fixture["dimension_units"]
    e_unit = units["E"][e_level]
    a_unit = units["A"][a_level]
    parts = [fixture["base_system_prompt"], f"E 维要求：{e_unit['instruction']}", f"A 维要求：{a_unit['instruction']}"]
    if shape == "instruction_only":
        return "\n\n".join(parts)
    if shape == "dimension_concat":
        parts.extend(
            [
                _dialogue_text("【E 维微型对话】", e_unit["dialogue"]),
                _dialogue_text("【A 维微型对话】", a_unit["dialogue"]),
            ]
        )
        return "\n\n".join(parts)
    if shape == "merged_dialogue":
        profile = fixture["merged_dialogues"][f"E_{e_level}_A_{a_level}"]
        parts.append(_dialogue_text("【合并人格微型对话】", profile["dialogue"]))
        return "\n\n".join(parts)
    raise ValueError(f"未知组装形态：{shape}")


def _marker_score(reply: str, markers: list[str]) -> int:
    """摘要：按预注册标记表计算回复分数。"""
    return sum(reply.count(marker) for marker in markers)


def score_reply(reply: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    """摘要：计算 E/A 方向分数与禁用标记命中。"""
    forbidden_hits = [marker for marker in evaluation["forbidden_markers"] if marker in reply]
    return {
        "extraversion_score": _marker_score(reply, evaluation["extraversion_markers"]),
        "agreeableness_score": _marker_score(reply, evaluation["agreeableness_markers"]),
        "forbidden_hits": forbidden_hits,
        "reply_chars": len(reply),
    }


def _mean(rows: list[dict[str, Any]], field: str) -> float:
    values = [float(row["scores"][field]) for row in rows]
    return sum(values) / len(values) if values else 0.0


def summarize(rows: list[dict[str, Any]], shapes: list[str]) -> dict[str, Any]:
    """摘要：按形态汇总四组方向检查与控制组 margin。"""
    summaries: dict[str, Any] = {}
    for shape in shapes:
        shape_rows = [row for row in rows if row["shape"] == shape]
        checks: list[dict[str, Any]] = []
        for a_level in ("high", "low"):
            high_rows = [row for row in shape_rows if row["e_level"] == "high" and row["a_level"] == a_level]
            low_rows = [row for row in shape_rows if row["e_level"] == "low" and row["a_level"] == a_level]
            high_mean = _mean(high_rows, "extraversion_score")
            low_mean = _mean(low_rows, "extraversion_score")
            checks.append(
                {
                    "dimension": "E",
                    "fixed_level": {"A": a_level},
                    "high_mean": round(high_mean, 6),
                    "low_mean": round(low_mean, 6),
                    "margin": round(high_mean - low_mean, 6),
                    "passed": high_mean > low_mean,
                }
            )
        for e_level in ("high", "low"):
            high_rows = [row for row in shape_rows if row["a_level"] == "high" and row["e_level"] == e_level]
            low_rows = [row for row in shape_rows if row["a_level"] == "low" and row["e_level"] == e_level]
            high_mean = _mean(high_rows, "agreeableness_score")
            low_mean = _mean(low_rows, "agreeableness_score")
            checks.append(
                {
                    "dimension": "A",
                    "fixed_level": {"E": e_level},
                    "high_mean": round(high_mean, 6),
                    "low_mean": round(low_mean, 6),
                    "margin": round(high_mean - low_mean, 6),
                    "passed": high_mean > low_mean,
                }
            )
        summaries[shape] = {
            "reply_count": len(shape_rows),
            "direction_checks": checks,
            "direction_pass_count": sum(check["passed"] for check in checks),
            "direction_margin_sum": round(sum(float(check["margin"]) for check in checks), 6),
            "forbidden_hit_count": sum(len(row["scores"]["forbidden_hits"]) for row in shape_rows),
            "mean_system_prompt_chars": round(
                sum(int(row["system_prompt_chars"]) for row in shape_rows) / len(shape_rows), 6
            ),
        }
    eligible = [shape for shape in ("dimension_concat", "merged_dialogue") if summaries[shape]["direction_pass_count"] == 4]
    ranked = sorted(
        eligible,
        key=lambda shape: (
            -float(summaries[shape]["direction_margin_sum"]),
            float(summaries[shape]["mean_system_prompt_chars"]),
            shape,
        ),
    )
    return {
        "shapes": summaries,
        "eligible_shapes": eligible,
        "automatic_candidate": ranked[0] if ranked else None,
        "requires_ta_naturalness_veto": bool(ranked),
    }


def run_preexperiment(fixture: dict[str, Any], backend_factory, max_tokens: int) -> dict[str, Any]:
    """摘要：执行固定矩阵并返回原始数据和汇总。"""
    rows: list[dict[str, Any]] = []
    for seed in fixture["seeds"]:
        print(f"[P1-EA] seed={seed} backend load", flush=True)
        backend = backend_factory(int(seed))
        for shape in fixture["shapes"]:
            for e_level, a_level in PROFILE_LEVELS:
                print(f"[P1-EA] seed={seed} shape={shape} E={e_level} A={a_level}", flush=True)
                system_prompt = build_system_prompt(fixture, shape, e_level, a_level)
                for prompt in fixture["prompts"]:
                    reply = backend.generate(
                        system_prompt=system_prompt,
                        history=[],
                        user_message=str(prompt["user"]),
                        memory_block="",
                        max_tokens=max_tokens,
                    )
                    rows.append(
                        {
                            "seed": int(seed),
                            "shape": shape,
                            "profile": f"E_{e_level}_A_{a_level}",
                            "e_level": e_level,
                            "a_level": a_level,
                            "prompt_id": prompt["id"],
                            "user": prompt["user"],
                            "reply": reply,
                            "system_prompt_chars": len(system_prompt),
                            "scores": score_reply(reply, fixture["evaluation"]),
                        }
                    )
    return {"rows": rows, "summary": summarize(rows, list(fixture["shapes"]))}


def main() -> int:
    """摘要：解析参数并运行 P1 微型预实验。"""
    parser = argparse.ArgumentParser(description="运行人格约束 P1 E/A 拼接微型预实验")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--backend", choices=("echo", "llama"), default="echo")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--n-ctx", type=int, default=2048)
    parser.add_argument("--n-gpu-layers", type=int, default=0)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))

    if args.backend == "echo":
        backend_factory = lambda seed: _EchoBackend()
    else:
        backend_factory = lambda seed: create_llama_backend(
            args.model,
            n_ctx=args.n_ctx,
            n_gpu_layers=args.n_gpu_layers,
            seed=seed,
        )
    payload = run_preexperiment(fixture, backend_factory, args.max_tokens)
    payload["meta"] = {
        "version": fixture["version"],
        "backend": args.backend,
        "model": str(args.model) if args.backend == "llama" else "echo",
        "seeds": fixture["seeds"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": str(args.fixture),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
