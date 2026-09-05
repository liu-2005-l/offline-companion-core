"""P3-0 L2 确认集第一段生成与盲化。

摘要：
    为四个 screening 候选生成 32 个全新 candidate-baseline 配对，执行冻结自动 gate，
    并按每格左右各四生成不泄露候选身份的外部盲审包。
"""

from __future__ import annotations

import argparse
import difflib
import gc
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import run_persona_constraint_p3_0_l2_screening as screening

DEFAULT_SPEC = REPO_ROOT / "fixtures" / "persona_constraints" / "p3_0_l2_confirmation_stage1_spec.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    """摘要：读取 YAML 顶层对象。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"YAML 顶层必须为对象：{path}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    """摘要：读取 JSON 顶层对象。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON 顶层必须为对象：{path}")
    return payload


def _repo_path(value: str) -> Path:
    """摘要：解析并约束 repo 相对路径。"""
    path = (REPO_ROOT / value).resolve()
    path.relative_to(REPO_ROOT)
    return path


def _sha256(path: Path) -> str:
    """摘要：计算文件 SHA-256。"""
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_context(stage_spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """摘要：加载 screening 规格与冻结源资产。"""
    screening_path = _repo_path(str(stage_spec["trace"]["screening_spec"]))
    screening_spec = _load_yaml(screening_path)
    return screening_spec, screening.load_sources(screening_spec)


def prompt_records(stage_spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """摘要：返回按维组织且绑定单一 fresh seed 的确认 prompt。"""
    result: dict[str, list[dict[str, Any]]] = {}
    for dimension, items in stage_spec["prompts"].items():
        result[str(dimension)] = [
            {
                "id": str(item["id"]),
                "scenario": str(item["scenario"]),
                "seed": int(item["seed"]),
                "text": str(item["text"]),
            }
            for item in items
        ]
    return result


def prompt_preflight(
    stage_spec: dict[str, Any],
    screening_spec: dict[str, Any],
    corpus: dict[str, Any],
) -> dict[str, Any]:
    """摘要：验证确认 prompt、seed 与 screening/P2 注入问句零复用。"""
    records = prompt_records(stage_spec)
    fresh_seeds = [int(value) for value in stage_spec["fresh_seeds"]]
    old_seeds = {
        int(value)
        for value in (
            list(screening_spec["generation"]["seeds"])
            + list(screening_spec["generation"]["previously_used_seeds"])
        )
    }
    prompt_ids = [item["id"] for items in records.values() for item in items]
    prompt_texts = [item["text"] for items in records.values() for item in items]
    assigned_seeds = [item["seed"] for items in records.values() for item in items]
    expected_seed_multiset = Counter({seed: len(records) for seed in fresh_seeds})
    assigned_seed_multiset = Counter(assigned_seeds)

    screening_prompts = [
        str(item["text"])
        for items in screening_spec["prompt_selection"]["prompts"].values()
        for item in items
    ]
    comparisons: list[dict[str, Any]] = []
    for dimension, items in records.items():
        injected_questions = [
            str(turn["user"])
            for level in screening_spec["assembly"]["target_levels"]
            for dialogue in corpus["dimension_units"][dimension][level]["dialogues"]
            for turn in dialogue["turns"]
        ]
        reference_prompts = screening_prompts + injected_questions
        for item in items:
            normalized = screening._compact_prompt(item["text"])
            ratios = []
            contained = False
            for reference in reference_prompts:
                normalized_reference = screening._compact_prompt(reference)
                ratios.append(
                    difflib.SequenceMatcher(None, normalized, normalized_reference, autojunk=False).ratio()
                )
                contained = contained or normalized in normalized_reference or normalized_reference in normalized
            comparisons.append(
                {
                    "prompt_id": item["id"],
                    "maximum_similarity": round(max(ratios), 6),
                    "contained": contained,
                    "passed": not contained and max(ratios) <= 0.75,
                }
            )

    checks = {
        "prompt_ids_unique": len(prompt_ids) == len(set(prompt_ids)),
        "prompt_texts_unique": len(prompt_texts) == len(set(prompt_texts)),
        "fresh_seeds_unique": len(fresh_seeds) == len(set(fresh_seeds)),
        "fresh_seeds_disjoint": not old_seeds.intersection(fresh_seeds),
        "one_seed_per_prompt_index": assigned_seed_multiset == expected_seed_multiset,
        "leakage_checks": all(item["passed"] for item in comparisons),
    }
    return {"passed": all(checks.values()), "checks": checks, "comparisons": comparisons}


def selected_candidates(stage_spec: dict[str, Any], verdict: dict[str, Any]) -> dict[str, str]:
    """摘要：核对 stage-1 候选与平衡 screening 裁决完全一致。"""
    configured = {str(target): str(arm) for target, arm in stage_spec["selected_candidates"].items()}
    frozen = {
        str(item["target"]): str(item["arm_id"])
        for item in verdict["selected_candidates"]
    }
    if configured != frozen:
        raise RuntimeError(f"stage-1 候选与 screening 裁决不一致：{configured} != {frozen}")
    return configured


def matrix_rows(
    stage_spec: dict[str, Any],
    screening_spec: dict[str, Any],
    verdict: dict[str, Any],
) -> list[dict[str, Any]]:
    """摘要：机械展开四格各八对、candidate 与 baseline 共 64 轮。"""
    candidates = selected_candidates(stage_spec, verdict)
    prompts = prompt_records(stage_spec)
    arms = {str(item["id"]): item for item in screening_spec["generation"]["candidate_arms"]}
    rows: list[dict[str, Any]] = []
    for target, candidate_arm_id in candidates.items():
        dimension, level = target.split("_", 1)
        for prompt in prompts[dimension]:
            for arm_id in ("baseline", candidate_arm_id):
                arm = arms[arm_id]
                rows.append(
                    {
                        "row_id": f"{target}-{arm_id}-{prompt['id']}-s{prompt['seed']}",
                        "target": target,
                        "dimension": dimension,
                        "level": level,
                        "arm_id": arm_id,
                        "parameter": str(arm["parameter"]),
                        "delta": float(arm["delta"]),
                        "prompt_id": prompt["id"],
                        "scenario": prompt["scenario"],
                        "user": prompt["text"],
                        "seed": prompt["seed"],
                        "decode": screening.decode_for_arm(screening_spec, arm),
                    }
                )
    expected = int(stage_spec["design"]["output_count"])
    if len(rows) != expected or len({row["row_id"] for row in rows}) != expected:
        raise RuntimeError(f"stage-1 矩阵不符：{len(rows)}/{expected}")
    return rows


def build_blind_review(
    stage_spec: dict[str, Any],
    corpus: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """摘要：生成每目标 candidate 左右各四的 32 对脱敏审包与封存键。"""
    salt = str(stage_spec["blind_review"]["salt"])
    by_key = {(row["target"], row["prompt_id"], row["arm_id"]): row for row in rows}
    candidates = [row for row in rows if row["arm_id"] != "baseline"]
    left_row_ids: set[str] = set()
    for target in stage_spec["selected_candidates"]:
        target_rows = [row for row in candidates if row["target"] == target]
        ranked = sorted(
            target_rows,
            key=lambda row: hashlib.sha256(f"{salt}|side|{row['row_id']}".encode()).hexdigest(),
        )
        if len(ranked) != 8:
            raise RuntimeError(f"{target} candidate 配对数不为 8")
        left_row_ids.update(row["row_id"] for row in ranked[:4])

    packet_rows = []
    key_rows = []
    for candidate in candidates:
        baseline = by_key[(candidate["target"], candidate["prompt_id"], "baseline")]
        candidate_left = candidate["row_id"] in left_row_ids
        left = candidate if candidate_left else baseline
        right = baseline if candidate_left else candidate
        blind_id = hashlib.sha256(f"{salt}|pair|{candidate['row_id']}".encode()).hexdigest()[:16]
        target_unit = corpus["dimension_units"][candidate["dimension"]][candidate["level"]]
        packet_rows.append(
            {
                "blind_id": blind_id,
                "dimension": candidate["dimension"],
                "level": candidate["level"],
                "target_intent": target_unit["intent"],
                "target_signatures": target_unit["signatures"],
                "scenario": candidate["scenario"],
                "prompt": candidate["user"],
                "left_reply": left["reply"],
                "right_reply": right["reply"],
                "review_choice": None,
                "review_note": "",
            }
        )
        key_rows.append(
            {
                "blind_id": blind_id,
                "target": candidate["target"],
                "arm_id": candidate["arm_id"],
                "candidate_side": "left" if candidate_left else "right",
                "candidate_row_id": candidate["row_id"],
                "baseline_row_id": baseline["row_id"],
                "candidate_automatic_gate": candidate["automatic_gate"],
                "baseline_automatic_gate": baseline["automatic_gate"],
            }
        )

    order = sorted(
        range(len(packet_rows)),
        key=lambda index: hashlib.sha256(
            f"{salt}|order|{packet_rows[index]['blind_id']}".encode()
        ).hexdigest(),
    )
    packet_rows = [packet_rows[index] for index in order]
    key_rows = [key_rows[index] for index in order]
    return (
        {
            "version": stage_spec["version"],
            "status": "pending_external_blind_review",
            "choices": stage_spec["blind_review"]["choices"],
            "instructions": "逐项选择更符合目标档位的一侧；不可区分或两侧均差选 indistinguishable。",
            "rows": packet_rows,
        },
        {
            "version": stage_spec["version"],
            "status": "sealed_until_external_review_complete",
            "placement": "four_left_four_right_per_target",
            "rows": key_rows,
        },
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """摘要：汇总生成与自动 gate，不泄露左右候选身份。"""
    targets = {}
    for target in sorted({str(row["target"]) for row in rows}):
        target_rows = [row for row in rows if row["target"] == target]
        targets[target] = {
            "outputs": len(target_rows),
            "automatic_green": sum(bool(row["automatic_passed"]) for row in target_rows),
            "gate_failures": Counter(
                gate
                for row in target_rows
                for gate, passed in row["automatic_gate"].items()
                if not passed
            ),
        }
    return {
        "output_count": len(rows),
        "automatic_green": sum(bool(row["automatic_passed"]) for row in rows),
        "targets": targets,
    }


def run(args: argparse.Namespace) -> int:
    """摘要：执行 stage-1 preflight、64 轮生成与 32 对盲化归档。"""
    stage_spec = _load_yaml(args.spec)
    screening_spec, sources = load_context(stage_spec)
    verdict_path = _repo_path(str(stage_spec["trace"]["balanced_screening_verdict"]))
    verdict = _load_json(verdict_path)
    output_dir = _repo_path(str(stage_spec["trace"]["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)

    screening_path = _repo_path(str(stage_spec["trace"]["screening_spec"]))
    model_path = _repo_path(str(screening_spec["trace"]["model_path"]))
    prompts = prompt_preflight(stage_spec, screening_spec, sources["dimension_corpus"])
    preflight = {
        "screening_spec_hash": _sha256(screening_path),
        "screening_spec_hash_passed": _sha256(screening_path)
        == stage_spec["trace"]["screening_spec_sha256"],
        "screening_verdict_hash": _sha256(verdict_path),
        "screening_verdict_hash_passed": _sha256(verdict_path)
        == stage_spec["trace"]["balanced_screening_verdict_sha256"],
        "model_hash": _sha256(model_path),
        "model_hash_passed": _sha256(model_path) == stage_spec["trace"]["model_sha256"],
        "prompts": prompts,
    }
    selected_candidates(stage_spec, verdict)
    preflight["passed"] = bool(
        preflight["screening_spec_hash_passed"]
        and preflight["screening_verdict_hash_passed"]
        and preflight["model_hash_passed"]
        and prompts["passed"]
    )
    screening._write_json(output_dir / "preflight_static.json", preflight)
    if not preflight["passed"]:
        print("[P3-0-L2-CONFIRM-1] 静态 preflight 失败", flush=True)
        return 2

    expected_rows = matrix_rows(stage_spec, screening_spec, verdict)
    if args.preflight_only:
        print("[P3-0-L2-CONFIRM-1] preflight passed", flush=True)
        return 0

    llama = screening._load_llama(screening_spec)
    probe_messages, _ = screening.build_messages(
        screening_spec,
        sources["dimension_corpus"],
        expected_rows[0],
    )
    rendered = screening.render_probe(llama, probe_messages)
    rendered["passed"] = rendered["chat_template_sha256"] == stage_spec["trace"]["chat_template_sha256"]
    screening._write_json(output_dir / "render_probe.json", rendered)
    if not rendered["passed"]:
        print("[P3-0-L2-CONFIRM-1] chat template preflight 失败", flush=True)
        return 3

    checkpoint_path = output_dir / "checkpoint.jsonl"
    expected_ids = {row["row_id"] for row in expected_rows}
    completed = screening._load_checkpoint(checkpoint_path, expected_ids)
    for index, row in enumerate(expected_rows, start=1):
        if row["row_id"] in completed:
            continue
        generated = screening._generate_one(llama, screening_spec, sources, row)
        with checkpoint_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(generated, ensure_ascii=False) + "\n")
            handle.flush()
        completed[row["row_id"]] = generated
        if index % 8 == 0 or index == len(expected_rows):
            print(f"[P3-0-L2-CONFIRM-1] progress {len(completed)}/{len(expected_rows)}", flush=True)

    del llama
    gc.collect()
    rows = [completed[row["row_id"]] for row in expected_rows]
    screening._write_jsonl(output_dir / "raw.jsonl", rows)
    screening._write_json(output_dir / "summary.json", summarize(rows))
    packet, key = build_blind_review(stage_spec, sources["dimension_corpus"], rows)
    screening._write_json(output_dir / "blind_review_packet.json", packet)
    screening._write_json(output_dir / "blind_review_key.json", key)
    print(f"[P3-0-L2-CONFIRM-1] completed outputs={len(rows)} pairs={len(packet['rows'])}", flush=True)
    return 0


def main() -> int:
    """摘要：解析命令行参数并执行确认集第一段。"""
    parser = argparse.ArgumentParser(description="运行 P3-0 L2 确认集第一段 32 对生成")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--preflight-only", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
