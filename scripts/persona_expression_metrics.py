"""拟人表述 W1 指标计算脚本。

摘要：
    对 W1 baseline 原始回复 JSON 重新计算六项风格指标。脚本只读取
    原始文本，不依赖 runner 内部状态，保证 baseline 可复算。
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

STYLE_SCENARIOS = {"chat", "memory"}
SENTENCE_SPLIT_RE = re.compile(r"[。！？；]+")
LIST_RE = re.compile(r"(?m)^\s*(?:[-*•]|[①-⑩]|[0-9]+[.、])\s+|^\s*#{1,6}\s+|^\s*\|.+\|\s*$")
TEMPLATE_PHRASES = (
    "作为一个AI",
    "作为一个语言模型",
    "总的来说",
    "综上所述",
    "希望这有所帮助",
    "希望对你有帮助",
    "值得注意的是",
    "让我们来",
    "接下来我将",
)
TRIPLE_TEMPLATE_MARKERS = ("首先", "其次", "最后")
COLLOQUIAL_MARKERS = (
    "吧",
    "呢",
    "啊",
    "嘛",
    "哦",
    "诶",
    "唉",
    "其实",
    "倒是",
    "毕竟",
    "说实话",
)
TING_PATTERN = re.compile(r"挺[\u4e00-\u9fff]{1,4}")


def first_sentence(text: str) -> str:
    """摘要：返回回复第一句文本，用于开场多样性统计。"""
    parts = SENTENCE_SPLIT_RE.split(text.strip(), maxsplit=1)
    return parts[0].strip() if parts else ""


def char_ngrams(text: str, size: int) -> set[str]:
    """摘要：返回文本的字符 n-gram 集合。"""
    compact = "".join(text.split())
    if len(compact) < size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def opening_distinct_2(replies: list[str]) -> float:
    """摘要：计算第一句前六字符的 bigram distinct-2。"""
    total = 0
    unique: set[str] = set()
    for reply in replies:
        opening = first_sentence(reply)[:6]
        grams = [opening[index : index + 2] for index in range(max(len(opening) - 1, 0))]
        total += len(grams)
        unique.update(grams)
    return len(unique) / total if total else 0.0


def sentence_lengths(text: str) -> list[int]:
    """摘要：按预注册句末标点切句并返回非空句长。"""
    return [len(part.strip()) for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]


def coefficient_of_variation(values: list[int]) -> float:
    """摘要：计算总体标准差除以均值的 CV。"""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance) / mean


def contains_list_structure(text: str) -> bool:
    """摘要：判断回复是否包含 bullet、编号、标题或 markdown 表格。"""
    return bool(LIST_RE.search(text))


def template_phrase_hits(text: str) -> int:
    """摘要：统计模板短语命中次数，含首先/其次/最后三连规则。"""
    hits = sum(text.count(phrase) for phrase in TEMPLATE_PHRASES)
    triple_count = sum(1 for marker in TRIPLE_TEMPLATE_MARKERS if marker in text)
    if triple_count >= 2:
        hits += 1
    return hits


def colloquial_marker_hits(text: str) -> int:
    """摘要：统计口语标记命中次数。"""
    hits = sum(text.count(marker) for marker in COLLOQUIAL_MARKERS)
    hits += len(TING_PATTERN.findall(text))
    return hits


def density_per_1000(hits: int, total_chars: int) -> float:
    """摘要：将命中数换算为每千字符密度。"""
    return hits * 1000 / total_chars if total_chars else 0.0


def jaccard(left: set[str], right: set[str]) -> float:
    """摘要：计算两个集合的 Jaccard 相似度。"""
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def _case_replies(case: dict[str, Any]) -> list[str]:
    replies = case.get("replies", [])
    return [str(reply) for reply in replies]


def _style_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [case for case in cases if str(case.get("scenario")) in STYLE_SCENARIOS]


def calculate_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """摘要：从 baseline JSON payload 计算六项 W1 风格指标。"""
    cases = list(payload.get("cases", []))
    style_cases = _style_cases(cases)
    style_replies = [reply for case in style_cases for reply in _case_replies(case)]
    all_text = "".join(style_replies)
    all_lengths = [length for reply in style_replies for length in sentence_lengths(reply)]
    per_case: dict[str, dict[str, Any]] = {}
    list_case_count = 0
    template_hits = 0
    colloquial_hits = 0
    for case in style_cases:
        replies = _case_replies(case)
        text = "\n".join(replies)
        has_list = contains_list_structure(text)
        list_case_count += int(has_list)
        case_template_hits = template_phrase_hits(text)
        case_colloquial_hits = colloquial_marker_hits(text)
        template_hits += case_template_hits
        colloquial_hits += case_colloquial_hits
        per_case[str(case.get("id"))] = {
            "opening_distinct_2": round(opening_distinct_2(replies), 6),
            "sentence_cv": round(
                coefficient_of_variation([length for reply in replies for length in sentence_lengths(reply)]),
                6,
            ),
            "contains_list_structure": has_list,
            "template_phrase_hits": case_template_hits,
            "colloquial_marker_hits": case_colloquial_hits,
            "chars": len(text),
        }

    group_scores: dict[str, float] = {}
    for case in style_cases:
        replies = _case_replies(case)
        if len(replies) < 2:
            continue
        scores = [
            jaccard(char_ngrams(replies[index], 4), char_ngrams(replies[index + 1], 4))
            for index in range(len(replies) - 1)
        ]
        group_scores[str(case.get("group") or case.get("id"))] = round(sum(scores) / len(scores), 6)
    cross_turn_mean = sum(group_scores.values()) / len(group_scores) if group_scores else 0.0
    per_case_cv = sorted(item["sentence_cv"] for item in per_case.values())
    median_cv = per_case_cv[len(per_case_cv) // 2] if per_case_cv else 0.0
    aggregate = {
        "style_case_count": len(style_cases),
        "style_reply_count": len(style_replies),
        "opening_distinct_2": round(opening_distinct_2(style_replies), 6),
        "sentence_cv": round(coefficient_of_variation(all_lengths), 6),
        "per_case_sentence_cv_median": round(median_cv, 6),
        "list_dependency_rate": round(list_case_count / len(style_cases), 6) if style_cases else 0.0,
        "template_phrase_density_per_1000": round(template_hits * 1000 / len(all_text), 6)
        if all_text
        else 0.0,
        "colloquial_marker_density_per_1000": round(colloquial_hits * 1000 / len(all_text), 6)
        if all_text
        else 0.0,
        "cross_turn_4gram_jaccard_mean": round(cross_turn_mean, 6),
        "cross_turn_4gram_jaccard_by_group": group_scores,
    }
    return {"aggregate": aggregate, "per_case": per_case}


def main() -> int:
    """摘要：命令行入口，读取 baseline JSON 并输出指标 JSON。"""
    parser = argparse.ArgumentParser(description="计算拟人表述 W1 六指标")
    parser.add_argument("input", type=Path, help="baseline 原始回复 JSON")
    parser.add_argument("--output", type=Path, help="指标输出路径；缺省打印到 stdout")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    metrics = calculate_metrics(payload)
    text = json.dumps(metrics, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
