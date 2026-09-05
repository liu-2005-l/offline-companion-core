"""人格约束 P3-0 L2 单维候选筛选。

摘要：
    按预注册的五维 low/high、八个采样 arm、两条 prompt 与两个 seed 生成 320 轮，
    执行冻结自动 gate，并输出隐藏参数身份的配对盲审包。
"""

from __future__ import annotations

import argparse
import difflib
import gc
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
for source_root in (SRC_ROOT, SCRIPTS_ROOT):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from run_persona_constraint_p2_form_preexperiment2 import (
    _formatter_for,
    detect_copy,
    scan_forbidden,
    scan_l4,
)

DEFAULT_SPEC = REPO_ROOT / "fixtures" / "persona_constraints" / "p3_0_l2_screening_spec.yaml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "persona_constraints" / "p3_0_l2_screening"
TERMINAL_CHARACTERS = frozenset("。！？!?…」』）》】")


def _load_yaml(path: Path) -> dict[str, Any]:
    """摘要：读取 YAML 顶层对象。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"YAML 顶层必须为对象：{path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    """摘要：稳定写入 UTF-8 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """摘要：稳定写入 UTF-8 JSONL。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def _sha256_file(path: Path) -> str:
    """摘要：流式计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _sha256_text(text: str) -> str:
    """摘要：计算 UTF-8 文本 SHA-256。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def _asset_path(asset: dict[str, Any]) -> Path:
    """摘要：解析规格中的 repo 相对资产路径。"""
    path = (REPO_ROOT / str(asset["path"])).resolve()
    path.relative_to(REPO_ROOT)
    return path


def load_sources(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """摘要：加载 screening 使用的四份冻结 YAML。"""
    return {
        name: _load_yaml(_asset_path(asset))
        for name, asset in spec["source_assets"].items()
    }


def selected_prompts(spec: dict[str, Any], corpus: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """摘要：读取每维两条预注册 held-out prompt。"""
    del corpus
    selection = spec["prompt_selection"]
    result: dict[str, list[dict[str, str]]] = {}
    for dimension in spec["assembly"]["dimension_order"]:
        prompts = [
            {
                "id": str(item["id"]),
                "scenario": str(item["scenario"]),
                "text": str(item["text"]),
                "source_unit": "held_out_preregistered",
            }
            for item in selection["prompts"][dimension]
        ]
        expected = int(selection["prompts_per_dimension"])
        if len(prompts) != expected:
            raise ValueError(f"{dimension} prompt 数量不符：{len(prompts)}/{expected}")
        result[str(dimension)] = prompts
    return result


def _compact_prompt(text: str) -> str:
    """摘要：折叠 prompt 空白与常见标点，供泄漏检查使用。"""
    return "".join(char for char in text.casefold() if not char.isspace() and char not in "，。！？?!；：、")


def prompt_leakage_checks(
    spec: dict[str, Any],
    corpus: dict[str, Any],
) -> list[dict[str, Any]]:
    """摘要：确保 held-out prompt 不与注入示例问句相同或近重复。"""
    threshold = float(spec["prompt_selection"]["leakage_check"]["maximum_sequence_similarity"])
    checks: list[dict[str, Any]] = []
    for dimension, prompts in selected_prompts(spec, corpus).items():
        examples = [
            str(turn["user"])
            for level in spec["assembly"]["target_levels"]
            for dialogue in corpus["dimension_units"][dimension][level]["dialogues"]
            for turn in dialogue["turns"]
        ]
        for prompt in prompts:
            normalized_prompt = _compact_prompt(prompt["text"])
            comparisons = []
            for example in examples:
                normalized_example = _compact_prompt(example)
                ratio = difflib.SequenceMatcher(None, normalized_prompt, normalized_example, autojunk=False).ratio()
                contained = normalized_prompt in normalized_example or normalized_example in normalized_prompt
                comparisons.append({"example": example, "ratio": round(ratio, 6), "contained": contained})
            worst = max(comparisons, key=lambda item: float(item["ratio"]))
            checks.append(
                {
                    "dimension": dimension,
                    "prompt_id": prompt["id"],
                    "prompt": prompt["text"],
                    "maximum_ratio": worst["ratio"],
                    "nearest_example": worst["example"],
                    "contained": any(bool(item["contained"]) for item in comparisons),
                    "passed": not any(bool(item["contained"]) for item in comparisons)
                    and float(worst["ratio"]) <= threshold,
                }
            )
    return checks


def decode_for_arm(spec: dict[str, Any], arm: dict[str, Any]) -> dict[str, float | int]:
    """摘要：以 baseline 为事实源生成单轴候选参数。"""
    decode = dict(spec["generation"]["baseline"])
    parameter = str(arm["parameter"])
    if parameter != "none":
        decode[parameter] = round(float(decode[parameter]) + float(arm["delta"]), 10)
    return decode


def matrix_rows(spec: dict[str, Any], corpus: dict[str, Any]) -> list[dict[str, Any]]:
    """摘要：按固定顺序展开 320 轮 screening 矩阵。"""
    prompts = selected_prompts(spec, corpus)
    rows: list[dict[str, Any]] = []
    for dimension in spec["assembly"]["dimension_order"]:
        for level in spec["assembly"]["target_levels"]:
            for arm in spec["generation"]["candidate_arms"]:
                for prompt in prompts[dimension]:
                    for seed in spec["generation"]["seeds"]:
                        rows.append(
                            {
                                "row_id": f"{dimension}-{level}-{arm['id']}-{prompt['id']}-s{seed}",
                                "dimension": str(dimension),
                                "level": str(level),
                                "arm_id": str(arm["id"]),
                                "parameter": str(arm["parameter"]),
                                "delta": float(arm["delta"]),
                                "prompt_id": prompt["id"],
                                "scenario": prompt["scenario"],
                                "user": prompt["text"],
                                "seed": int(seed),
                                "decode": decode_for_arm(spec, arm),
                            }
                        )
    return rows


def _render_dialogues(unit: dict[str, Any]) -> tuple[str, list[str]]:
    """摘要：把目标档位全部微型对话渲染为 system 文本。"""
    lines: list[str] = []
    assistant_examples: list[str] = []
    for dialogue_index, dialogue in enumerate(unit["dialogues"], start=1):
        lines.append(f"示例组 {dialogue_index}（{dialogue['scenario']}）：")
        for turn_index, turn in enumerate(dialogue["turns"], start=1):
            lines.append(f"用户 {turn_index}：{turn['user']}")
            lines.append(f"助手 {turn_index}：{turn['assistant']}")
            assistant_examples.append(str(turn["assistant"]))
    return "\n".join(lines), assistant_examples


def build_messages(
    spec: dict[str, Any],
    corpus: dict[str, Any],
    row: dict[str, Any],
) -> tuple[list[dict[str, str]], list[str]]:
    """摘要：按 F0b system 内嵌形态构造单维标定消息。"""
    unit = corpus["dimension_units"][row["dimension"]][row["level"]]
    dialogue_block, examples = _render_dialogues(unit)
    system_prompt = "\n\n".join(
        (
            str(spec["assembly"]["base_system_prompt"]),
            f"【目标维度】{row['dimension']} / {row['level']}\n{unit['intent']}",
            f"【目标档位微型对话】\n{dialogue_block}",
        )
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": str(row["user"])},
    ], examples


def static_preflight(
    spec: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """摘要：核验输入哈希、矩阵结构和冻结检测器正负控。"""
    hash_rows = []
    for name, asset in spec["source_assets"].items():
        actual = _sha256_file(_asset_path(asset))
        hash_rows.append(
            {"asset": name, "expected": str(asset["sha256"]), "actual": actual, "passed": actual == asset["sha256"]}
        )

    corpus = sources["dimension_corpus"]
    lexicon = sources["lexicon"]
    patterns = sources["l4_patterns"]
    l4_baseline = sources["l4_baseline"]
    rows = matrix_rows(spec, corpus)
    expected_rows = int(spec["matrix"]["total_output_count"])
    row_ids_unique = len({row["row_id"] for row in rows}) == len(rows)

    corpus_scans: list[dict[str, Any]] = []
    for dimension in spec["assembly"]["dimension_order"]:
        for level in spec["assembly"]["target_levels"]:
            unit = corpus["dimension_units"][dimension][level]
            text = "\n".join(
                str(turn["assistant"])
                for dialogue in unit["dialogues"]
                for turn in dialogue["turns"]
            )
            corpus_scans.append(
                {
                    "unit": unit["id"],
                    "forbidden_hits": scan_forbidden(text, lexicon),
                    "l4": scan_l4(text, patterns),
                }
            )

    l4_rows: list[dict[str, Any]] = []
    for pair in l4_baseline["pairs"]:
        for polarity in ("positive", "negative"):
            sample = pair[polarity]
            verdict = scan_l4(
                str(sample["text"]),
                patterns,
                display_name_present=bool(sample.get("display_name_present", False)),
            )
            l4_rows.append(
                {
                    "id": pair["id"],
                    "polarity": polarity,
                    "expected_zone": pair["zone"],
                    "expected_family": pair["family"],
                    "verdict": verdict,
                }
            )
    true_positives = sum(
        row["polarity"] == "positive"
        and row["verdict"]["zone"] == row["expected_zone"]
        and row["verdict"]["family"] == row["expected_family"]
        for row in l4_rows
    )
    false_positives = sum(row["polarity"] == "negative" and row["verdict"]["hit"] for row in l4_rows)
    detector_hits = scan_forbidden(str(spec["preflight"]["detector_positive_control"]), lexicon)
    copy_probe = detect_copy(
        str(spec["preflight"]["copy_positive_reply"]),
        [str(spec["preflight"]["copy_positive_example"])],
        6,
    )
    leakage_checks = prompt_leakage_checks(spec, corpus)
    passed = (
        all(item["passed"] for item in hash_rows)
        and len(rows) == expected_rows
        and row_ids_unique
        and bool(detector_hits)
        and bool(copy_probe["hit"])
        and all(item["passed"] for item in leakage_checks)
        and all(not item["forbidden_hits"] and not item["l4"]["hit"] for item in corpus_scans)
        and true_positives == int(spec["preflight"]["l4_expected_true_positives"])
        and false_positives == int(spec["preflight"]["l4_expected_false_positives"])
    )
    return {
        "version": spec["version"],
        "passed": passed,
        "source_hashes": hash_rows,
        "matrix": {"actual": len(rows), "expected": expected_rows, "row_ids_unique": row_ids_unique},
        "selected_prompts": selected_prompts(spec, corpus),
        "prompt_leakage_checks": leakage_checks,
        "detector_probe_hits": detector_hits,
        "copy_probe": copy_probe,
        "corpus_scans": corpus_scans,
        "l4": {"true_positives": true_positives, "false_positives": false_positives, "rows": l4_rows},
    }


def _load_llama(spec: dict[str, Any]) -> Any:
    """摘要：按预注册模型参数加载 llama-cpp。"""
    from llama_cpp import Llama

    generation = spec["generation"]
    return Llama(
        model_path=str(REPO_ROOT / spec["trace"]["model_path"]),
        n_ctx=int(generation["n_ctx"]),
        n_gpu_layers=int(generation["n_gpu_layers"]),
        verbose=False,
    )


def render_probe(llama: Any, messages: list[dict[str, str]]) -> dict[str, Any]:
    """摘要：归档当前 GGUF chat template 的真实渲染结果。"""
    formatter = _formatter_for(llama)
    rendered = formatter(messages=messages).prompt
    template = str(llama.metadata.get("tokenizer.chat_template") or "")
    return {
        "chat_format": llama.chat_format,
        "chat_template_sha256": _sha256_text(template),
        "messages": messages,
        "rendered_prompt": rendered,
        "prompt_tokens": len(llama.tokenize(rendered.encode("utf-8"), add_bos=False, special=True)),
    }


def _complete_terminal(reply: str) -> bool:
    """摘要：判断对话回复是否以完整终止符结束。"""
    return bool(reply) and reply.rstrip()[-1] in TERMINAL_CHARACTERS


def _generate_one(
    llama: Any,
    spec: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    row: dict[str, Any],
) -> dict[str, Any]:
    """摘要：执行单轮并附加全部自动 gate 证据。"""
    messages, examples = build_messages(spec, sources["dimension_corpus"], row)
    formatter = _formatter_for(llama)
    rendered = formatter(messages=messages).prompt
    prompt_tokens = len(llama.tokenize(rendered.encode("utf-8"), add_bos=False, special=True))
    max_tokens = int(spec["generation"]["max_tokens"])
    if prompt_tokens + max_tokens > int(spec["generation"]["n_ctx"]):
        raise RuntimeError(f"上下文超限：{row['row_id']} prompt={prompt_tokens} max={max_tokens}")

    decode = row["decode"]
    started = time.perf_counter()
    output = llama.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        seed=int(row["seed"]),
        temperature=float(decode["temperature"]),
        top_p=float(decode["top_p"]),
        top_k=int(decode["top_k"]),
        min_p=float(decode["min_p"]),
        typical_p=float(decode["typical_p"]),
        presence_penalty=float(decode["presence_penalty"]),
        frequency_penalty=float(decode["frequency_penalty"]),
        repeat_penalty=float(decode["repeat_penalty"]),
    )
    elapsed = time.perf_counter() - started
    choice = output["choices"][0]
    reply = str(choice["message"]["content"] or "").strip()
    output_tokens = len(llama.tokenize(reply.encode("utf-8"), add_bos=False, special=True))
    forbidden_hits = scan_forbidden(reply, sources["lexicon"])
    l4 = scan_l4(reply, sources["l4_patterns"])
    l4_action = sources["l4_patterns"]["zones"].get(l4["zone"], {}).get("action") if l4["hit"] else None
    copy = detect_copy(reply, examples, output_tokens)
    finish_reason = choice.get("finish_reason")
    automatic_gate = {
        "forbidden": not forbidden_hits,
        "l4_retry_then_fallback": l4_action != "retry_then_fallback",
        "copy": not copy["hit"],
        "finish": finish_reason in spec["automatic_gates"]["allowed_finish_reasons"],
        "nonempty": bool(reply),
        "complete_terminal": _complete_terminal(reply),
    }
    return {
        **row,
        "reply": reply,
        "finish_reason": finish_reason,
        "prompt_tokens": int(output.get("usage", {}).get("prompt_tokens", prompt_tokens)),
        "completion_tokens": int(output.get("usage", {}).get("completion_tokens", output_tokens)),
        "elapsed_seconds": round(elapsed, 6),
        "forbidden_hits": forbidden_hits,
        "l4": {**l4, "action": l4_action},
        "copy": copy,
        "complete_terminal": _complete_terminal(reply),
        "automatic_gate": automatic_gate,
        "automatic_passed": all(automatic_gate.values()),
    }


def _pair_id(row: dict[str, Any], namespace: str) -> str:
    """摘要：返回不暴露 arm 的稳定盲审 ID。"""
    raw = (
        f"{namespace}|{row['dimension']}|{row['level']}|{row['prompt_id']}|"
        f"{row['seed']}|{row['arm_id']}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_blind_review(
    spec: dict[str, Any],
    corpus: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    blind_salt: str | None = None,
    review_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """摘要：按每 arm 左右各半生成配对盲审包及独立解盲键。"""
    row_index = {
        (row["dimension"], row["level"], row["prompt_id"], row["seed"], row["arm_id"]): row
        for row in rows
    }
    review_rows: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    salt = blind_salt or str(spec["screening_review"]["blind_salt"])
    version = review_version or str(spec["version"])
    candidate_arms = [arm for arm in spec["generation"]["candidate_arms"] if arm["id"] != "baseline"]
    placement_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row["arm_id"] == "baseline":
            continue
        group_key = (str(row["dimension"]), str(row["level"]), str(row["arm_id"]))
        placement_groups.setdefault(group_key, []).append(row)

    candidate_left_ids: set[str] = set()
    for group_key, arm_rows in placement_groups.items():
        if len(arm_rows) != 4:
            raise RuntimeError(f"盲审 arm 必须恰有四轮：{group_key}={len(arm_rows)}")
        ranked = sorted(
            arm_rows,
            key=lambda item: hashlib.sha256(
                f"{salt}|balanced-side|{item['row_id']}".encode()
            ).hexdigest(),
        )
        candidate_left_ids.update(item["row_id"] for item in ranked[:2])

    for row in rows:
        if row["arm_id"] == "baseline":
            continue
        baseline = row_index[(row["dimension"], row["level"], row["prompt_id"], row["seed"], "baseline")]
        blind_id = _pair_id(row, salt)
        candidate_left = row["row_id"] in candidate_left_ids
        left = row if candidate_left else baseline
        right = baseline if candidate_left else row
        target = corpus["dimension_units"][row["dimension"]][row["level"]]
        review_rows.append(
            {
                "blind_id": blind_id,
                "dimension": row["dimension"],
                "level": row["level"],
                "target_intent": target["intent"],
                "target_signatures": target["signatures"],
                "scenario": row["scenario"],
                "prompt": row["user"],
                "left_reply": left["reply"],
                "right_reply": right["reply"],
                "candidate_automatic_passed": row["automatic_passed"],
                "review_choice": None,
                "review_note": "",
            }
        )
        key_rows.append(
            {
                "blind_id": blind_id,
                "arm_id": row["arm_id"],
                "candidate_side": "left" if candidate_left else "right",
                "candidate_row_id": row["row_id"],
                "baseline_row_id": baseline["row_id"],
            }
        )
    expected_pairs = int(spec["matrix"]["nonbaseline_pair_count"])
    if len(review_rows) != expected_pairs or len(candidate_arms) != 7:
        raise RuntimeError(f"盲审配对数不符：{len(review_rows)}/{expected_pairs}")
    packet = {
        "version": version,
        "status": "pending_ta_screening_review",
        "choices": spec["screening_review"]["choices"],
        "instructions": "逐项选择更符合目标档位的一侧；不可区分选 indistinguishable。自动 gate 红项不进入候选。",
        "rows": review_rows,
    }
    key = {
        "version": version,
        "placement": "balanced_two_left_two_right_per_arm",
        "rows": key_rows,
    }
    return packet, key


def rebuild_balanced_review(
    spec: dict[str, Any],
    corpus: dict[str, Any],
    output_dir: Path,
    *,
    blind_salt: str,
    review_version: str,
    suffix: str,
) -> tuple[Path, Path]:
    """摘要：复用冻结原始输出，重建每 arm 左右各半的盲审包与解盲键。

    参数：
        spec: screening 冻结规格。
        corpus: P2 冻结维度语料。
        output_dir: 已完成 screening 的证据目录。
        blind_salt: 新一轮盲化命名空间与排序盐。
        review_version: 新盲审包版本。
        suffix: 新文件名后缀。

    返回值：
        新盲审包路径与解盲键路径。
    """
    raw_path = output_dir / "raw.jsonl"
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line]
    expected_ids = {row["row_id"] for row in matrix_rows(spec, corpus)}
    actual_ids = {str(row["row_id"]) for row in rows}
    if len(rows) != len(expected_ids) or actual_ids != expected_ids:
        raise RuntimeError("冻结 raw 与 screening 规格不一致，禁止重建盲审包")

    packet_all, key = build_blind_review(
        spec,
        corpus,
        rows,
        blind_salt=blind_salt,
        review_version=review_version,
    )
    packet = filter_eligible_review(packet_all, key, rows)
    packet_path = output_dir / f"blind_review_packet_{suffix}.json"
    key_path = output_dir / f"blind_review_key_{suffix}.json"
    _write_json(packet_path, packet)
    _write_json(key_path, key)
    return packet_path, key_path


def filter_eligible_review(
    packet: dict[str, Any],
    key: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """摘要：仅保留四轮自动 gate 全绿的 candidate arm，且不泄露 arm 身份。"""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row["arm_id"] == "baseline":
            continue
        group_key = (str(row["dimension"]), str(row["level"]), str(row["arm_id"]))
        grouped.setdefault(group_key, []).append(row)
    eligible_rows = {
        row["row_id"]
        for arm_rows in grouped.values()
        if len(arm_rows) == 4 and all(bool(row["automatic_passed"]) for row in arm_rows)
        for row in arm_rows
    }
    eligible_blind_ids = {
        item["blind_id"]
        for item in key["rows"]
        if item["candidate_row_id"] in eligible_rows
    }
    selected = [item for item in packet["rows"] if item["blind_id"] in eligible_blind_ids]
    return {
        **{name: value for name, value in packet.items() if name != "rows"},
        "status": "pending_ta_screening_review_eligible_only",
        "instructions": (
            "本包只含四轮自动 gate 全绿的 candidate arm。逐项选择更符合目标档位的一侧；"
            "不可区分选 indistinguishable。"
        ),
        "rows": selected,
    }


def summarize(spec: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """摘要：按目标格与 candidate arm 汇总自动 gate，等待 TA 方向审读。"""
    targets: dict[str, Any] = {}
    for dimension in spec["assembly"]["dimension_order"]:
        for level in spec["assembly"]["target_levels"]:
            target_id = f"{dimension}_{level}"
            target_rows = [row for row in rows if row["dimension"] == dimension and row["level"] == level]
            arms: dict[str, Any] = {}
            for arm in spec["generation"]["candidate_arms"]:
                arm_rows = [row for row in target_rows if row["arm_id"] == arm["id"]]
                gate_failures = Counter(
                    gate
                    for row in arm_rows
                    for gate, passed in row["automatic_gate"].items()
                    if not passed
                )
                arms[str(arm["id"])] = {
                    "row_count": len(arm_rows),
                    "automatic_all_passed": all(row["automatic_passed"] for row in arm_rows),
                    "gate_failures": dict(gate_failures),
                    "forbidden_hit_rows": sum(bool(row["forbidden_hits"]) for row in arm_rows),
                    "l4_retry_rows": sum(row["l4"]["action"] == "retry_then_fallback" for row in arm_rows),
                    "l4_observe_rows": sum(row["l4"]["action"] == "observe_only" for row in arm_rows),
                    "copy_hit_rows": sum(bool(row["copy"]["hit"]) for row in arm_rows),
                    "elapsed_seconds": round(sum(float(row["elapsed_seconds"]) for row in arm_rows), 6),
                }
            targets[target_id] = {"row_count": len(target_rows), "arms": arms}
    return {
        "version": spec["version"],
        "status": "pending_ta_screening_review",
        "total_rows": len(rows),
        "automatic_passed_rows": sum(row["automatic_passed"] for row in rows),
        "targets": targets,
    }


def _load_checkpoint(path: Path, expected_ids: set[str]) -> dict[str, dict[str, Any]]:
    """摘要：读取可恢复 checkpoint 并拒绝规格外行。"""
    if not path.is_file():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {str(row["row_id"]): row for row in rows}
    if len(by_id) != len(rows) or not set(by_id).issubset(expected_ids):
        raise RuntimeError("checkpoint 含重复或规格外 row_id")
    return by_id


def run(args: argparse.Namespace) -> int:
    """摘要：执行 preflight、320 轮生成、自动汇总与盲审包归档。"""
    spec = _load_yaml(args.spec)
    sources = load_sources(spec)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    preflight = static_preflight(spec, sources)
    model_path = (REPO_ROOT / str(spec["trace"]["model_path"])).resolve()
    model_hash = _sha256_file(model_path)
    preflight["model"] = {
        "path": str(model_path),
        "expected_sha256": spec["trace"]["model_sha256"],
        "actual_sha256": model_hash,
        "passed": model_hash == spec["trace"]["model_sha256"],
    }
    preflight["passed"] = bool(preflight["passed"] and preflight["model"]["passed"])
    _write_json(output_dir / "preflight_static.json", preflight)
    if not preflight["passed"]:
        print("[P3-0-L2] 静态 preflight 失败", flush=True)
        return 2

    llama = _load_llama(spec)
    first_row = matrix_rows(spec, sources["dimension_corpus"])[0]
    probe_messages, _ = build_messages(spec, sources["dimension_corpus"], first_row)
    rendered = render_probe(llama, probe_messages)
    rendered["passed"] = (
        rendered["chat_format"] == spec["trace"]["chat_format"]
        and rendered["chat_template_sha256"] == spec["trace"]["chat_template_sha256"]
    )
    _write_json(output_dir / "render_probe.json", rendered)
    if not rendered["passed"]:
        print("[P3-0-L2] chat template preflight 失败", flush=True)
        return 3
    if args.preflight_only:
        print("[P3-0-L2] preflight passed", flush=True)
        return 0

    expected_rows = matrix_rows(spec, sources["dimension_corpus"])
    expected_ids = {row["row_id"] for row in expected_rows}
    checkpoint_path = output_dir / "checkpoint.jsonl"
    completed = _load_checkpoint(checkpoint_path, expected_ids)
    for index, row in enumerate(expected_rows, start=1):
        if row["row_id"] in completed:
            continue
        generated = _generate_one(llama, spec, sources, row)
        with checkpoint_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(generated, ensure_ascii=False) + "\n")
            handle.flush()
        completed[row["row_id"]] = generated
        if index % 10 == 0 or index == len(expected_rows):
            print(f"[P3-0-L2] progress {len(completed)}/{len(expected_rows)}", flush=True)

    del llama
    gc.collect()
    rows = [completed[row["row_id"]] for row in expected_rows]
    _write_jsonl(output_dir / "raw.jsonl", rows)
    _write_json(output_dir / "summary.json", summarize(spec, rows))
    packet_all, key = build_blind_review(spec, sources["dimension_corpus"], rows)
    packet = filter_eligible_review(packet_all, key, rows)
    _write_json(output_dir / "blind_review_packet_all.json", packet_all)
    _write_json(output_dir / "blind_review_packet.json", packet)
    _write_json(output_dir / "blind_review_key.json", key)
    print(f"[P3-0-L2] completed rows={len(rows)} review_pairs={len(packet['rows'])}", flush=True)
    return 0


def main() -> int:
    """摘要：解析命令行参数并执行 P3-0 L2 screening。"""
    parser = argparse.ArgumentParser(description="运行人格约束 P3-0 L2 320 轮 screening")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--preflight-only", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
