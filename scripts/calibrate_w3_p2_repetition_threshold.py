"""摘要：扫描 W3-P2 跨轮复读门的零误拦阈值与比较符号。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offline_companion.core.persona_session.repetition_guard import (
    CROSS_TURN_REPETITION_NGRAM_SIZE,
    CrossTurnRepetitionComparison,
    cross_turn_repetition_score,
    decide_cross_turn_repetition,
    detect_confirmation_intent,
)

DEFAULT_FIXTURE = ROOT / "fixtures" / "persona_expression" / "w3_p2_repetition_pairs.json"
ANCHOR_TOLERANCE = 0.0000005


@dataclass(frozen=True)
class CalibrationResult:
    """摘要：记录零误拦阈值扫描的机械产物。

    参数：
        decision: 是否存在至少召回一个正例的零误拦候选。
        threshold: 推荐阈值。
        comparison: 推荐比较符号。
        positive_count: 正例数量。
        negative_count: 负例数量。
        true_positive_ids: 被推荐候选命中的正例 ID。
        false_positive_ids: 被错误命中的负例 ID。
        false_negative_ids: 未命中的正例 ID。
        max_negative_score: 负例最高分。
        max_negative_ids: 达到负例最高分的判别对 ID。
        max_positive_score: 正例最高分。
        evaluated_candidate_count: 实际扫描的阈值与比较符号组合数。
        anchor_count: 完成预期得分自检的归档样本数。
        exempt_negative_ids: 由生产判定路径豁免、但仍留在负例分母的 ID。
        true_negative_count: 未触发且未豁免的普通真负例数量。
    """

    decision: str
    threshold: float
    comparison: CrossTurnRepetitionComparison
    positive_count: int
    negative_count: int
    true_positive_ids: tuple[str, ...]
    false_positive_ids: tuple[str, ...]
    false_negative_ids: tuple[str, ...]
    max_negative_score: float
    max_negative_ids: tuple[str, ...]
    max_positive_score: float
    evaluated_candidate_count: int
    anchor_count: int
    exempt_negative_ids: tuple[str, ...] = ()
    true_negative_count: int = 0


@dataclass(frozen=True)
class _CandidateResult:
    """摘要：记录一个阈值与比较符号组合的精确混淆路径。"""

    threshold: float
    comparison: CrossTurnRepetitionComparison
    true_positive_ids: tuple[str, ...]
    false_positive_ids: tuple[str, ...]
    false_negative_ids: tuple[str, ...]
    exempt_negative_ids: tuple[str, ...]
    true_negative_count: int


def _load_fixture(path: Path) -> dict[str, Any]:
    """摘要：读取并校验判别 fixture 的根结构。"""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("fixture_root_must_be_object")
    if data.get("ngram_size") != CROSS_TURN_REPETITION_NGRAM_SIZE:
        raise ValueError("fixture_ngram_size_mismatch")
    if data.get("version") != "0.2":
        raise ValueError("fixture_version_mismatch")
    positive = data.get("positive")
    negative = data.get("negative")
    if not isinstance(positive, list) or not positive:
        raise TypeError("fixture_positive_must_be_non_empty_list")
    if not isinstance(negative, list) or not negative:
        raise TypeError("fixture_negative_must_be_non_empty_list")
    seen_ids: set[str] = set()
    for pair in [*positive, *negative]:
        if not isinstance(pair, dict):
            raise TypeError("fixture_pair_must_be_object")
        pair_id = str(pair.get("id") or "")
        if not pair_id or pair_id in seen_ids:
            raise ValueError("fixture_pair_id_invalid")
        seen_ids.add(pair_id)
        if not str(pair.get("previous_reply") or "") or not str(pair.get("current_reply") or ""):
            raise ValueError(f"fixture_pair_text_missing:{pair_id}")
        if "user_message" not in pair or not isinstance(pair["user_message"], str):
            raise ValueError(f"fixture_pair_field_missing:{pair_id}:user_message")
        if "expects_user_confirmation" not in pair or not isinstance(
            pair["expects_user_confirmation"], bool
        ):
            raise ValueError(
                f"fixture_pair_field_missing:{pair_id}:expects_user_confirmation"
            )
        actual_intent = detect_confirmation_intent(pair["user_message"])
        if actual_intent != pair["expects_user_confirmation"]:
            raise ValueError(f"fixture_intent_label_mismatch:{pair_id}")
    return data


def _score_pair(pair: dict[str, Any]) -> float:
    """摘要：计算单个判别对得分。"""

    return cross_turn_repetition_score(
        str(pair["previous_reply"]),
        str(pair["current_reply"]),
    )


def _verify_anchors(pairs: list[dict[str, Any]]) -> int:
    """摘要：核对归档判别对的预期得分，防止文本或口径漂移。"""

    checked = 0
    for pair in pairs:
        if "expected_score" not in pair:
            continue
        expected = float(pair["expected_score"])
        actual = _score_pair(pair)
        if abs(actual - expected) > ANCHOR_TOLERANCE:
            raise ValueError(
                f"fixture_anchor_mismatch:{pair['id']}:expected={expected:.6f}:actual={actual:.6f}"
            )
        checked += 1
    return checked


def _triggered_ids(
    pairs: list[dict[str, Any]],
    *,
    threshold: float,
    comparison: CrossTurnRepetitionComparison,
    use_intent: bool,
) -> tuple[str, ...]:
    """摘要：返回通过生产判定路径命中的判别对 ID。"""

    return tuple(
        str(pair["id"])
        for pair in pairs
        if decide_cross_turn_repetition(
            str(pair["previous_reply"]),
            str(pair["current_reply"]),
            threshold=threshold,
            comparison=comparison,
            user_message=str(pair["user_message"]) if use_intent else None,
        ).action
        == "retry"
    )


def _candidate_result(
    positive: list[dict[str, Any]],
    negative: list[dict[str, Any]],
    *,
    threshold: float,
    comparison: CrossTurnRepetitionComparison,
    use_intent: bool,
) -> _CandidateResult:
    """摘要：通过生产判定路径计算一个候选的完整混淆 ID。"""

    true_positive_ids = _triggered_ids(
        positive,
        threshold=threshold,
        comparison=comparison,
        use_intent=use_intent,
    )
    false_positive_ids = _triggered_ids(
        negative,
        threshold=threshold,
        comparison=comparison,
        use_intent=use_intent,
    )
    negative_decisions = {
        str(pair["id"]): decide_cross_turn_repetition(
            str(pair["previous_reply"]),
            str(pair["current_reply"]),
            threshold=threshold,
            comparison=comparison,
            user_message=str(pair["user_message"]) if use_intent else None,
        )
        for pair in negative
    }
    exempt_negative_ids = tuple(
        pair_id
        for pair_id, decision in negative_decisions.items()
        if decision.action == "bypass" and decision.reason == "user_confirmation_exempt"
    )
    true_negative_count = sum(
        decision.action == "direct" for decision in negative_decisions.values()
    )
    triggered_positive_ids = set(true_positive_ids)
    false_negative_ids = tuple(
        str(pair["id"])
        for pair in positive
        if str(pair["id"]) not in triggered_positive_ids
    )
    return _CandidateResult(
        threshold=threshold,
        comparison=comparison,
        true_positive_ids=true_positive_ids,
        false_positive_ids=false_positive_ids,
        false_negative_ids=false_negative_ids,
        exempt_negative_ids=exempt_negative_ids,
        true_negative_count=true_negative_count,
    )


def _calibrate_mode(
    data: dict[str, Any],
    *,
    use_intent: bool,
    anchor_count: int,
) -> CalibrationResult:
    """摘要：按一个意图口径扫描零误拦候选。

    参数：
        data: 已通过结构与标签校验的 fixture。
        use_intent: 是否让生产判定路径消费真实用户输入。
        anchor_count: 已核对的归档得分锚数量。

    返回值：
        单口径校准结果。
    """

    positive = list(data["positive"])
    negative = list(data["negative"])
    positive_scores = {str(pair["id"]): _score_pair(pair) for pair in positive}
    negative_scores = {str(pair["id"]): _score_pair(pair) for pair in negative}
    effective_negative_scores = {
        str(pair["id"]): negative_scores[str(pair["id"])]
        for pair in negative
        if decide_cross_turn_repetition(
            str(pair["previous_reply"]),
            str(pair["current_reply"]),
            threshold=1.0,
            comparison="gt",
            user_message=str(pair["user_message"]) if use_intent else None,
        ).reason
        != "user_confirmation_exempt"
    }
    max_negative_score = max(effective_negative_scores.values())
    max_negative_ids = tuple(
        pair_id
        for pair_id, score in effective_negative_scores.items()
        if score == max_negative_score
    )
    thresholds = sorted({0.0, 1.0, *positive_scores.values(), *negative_scores.values()})
    candidates = [
        _candidate_result(
            positive,
            negative,
            threshold=threshold,
            comparison=comparison,
            use_intent=use_intent,
        )
        for threshold in thresholds
        for comparison in ("gt", "gte")
    ]
    zero_fp_candidates = [candidate for candidate in candidates if not candidate.false_positive_ids]
    if not zero_fp_candidates:
        raise RuntimeError("zero_fp_candidate_missing")
    selected = min(
        zero_fp_candidates,
        key=lambda candidate: (
            -len(candidate.true_positive_ids),
            candidate.threshold,
            candidate.comparison != "gt",
        ),
    )
    decision = "zero_fp_candidate" if selected.true_positive_ids else "zero_fp_no_recall"
    return CalibrationResult(
        decision=decision,
        threshold=selected.threshold,
        comparison=selected.comparison,
        positive_count=len(positive),
        negative_count=len(negative),
        true_positive_ids=selected.true_positive_ids,
        false_positive_ids=selected.false_positive_ids,
        false_negative_ids=selected.false_negative_ids,
        max_negative_score=max_negative_score,
        max_negative_ids=max_negative_ids,
        max_positive_score=max(positive_scores.values()),
        evaluated_candidate_count=len(candidates),
        anchor_count=anchor_count,
        exempt_negative_ids=selected.exempt_negative_ids,
        true_negative_count=selected.true_negative_count,
    )


def calibrate(data: dict[str, Any]) -> dict[str, CalibrationResult]:
    """摘要：生成 strict 与 intent-aware 双口径校准结果。

    参数：
        data: 已通过结构与标签校验的 fixture。

    返回值：
        以 ``strict`` 和 ``intent_aware`` 为键的校准结果。

    Raises:
        RuntimeError: strict 无豁免结论偏离已冻结的无召回形态。
    """

    anchor_count = _verify_anchors([*data["positive"], *data["negative"]])
    strict = _calibrate_mode(data, use_intent=False, anchor_count=anchor_count)
    if strict.decision != "zero_fp_no_recall":
        raise RuntimeError("strict_decision_drift")
    intent_aware = _calibrate_mode(data, use_intent=True, anchor_count=anchor_count)
    return {"strict": strict, "intent_aware": intent_aware}


def _print_result(
    fixture: Path,
    mode: str,
    result: CalibrationResult,
) -> None:
    """摘要：输出一个口径的稳定人工审阅校准摘要。"""

    prefix = f"{mode}."
    print(f"{prefix}fixture={fixture}")
    print(f"{prefix}ngram_size={CROSS_TURN_REPETITION_NGRAM_SIZE}")
    print(f"{prefix}positive_count={result.positive_count}")
    print(f"{prefix}negative_count={result.negative_count}")
    print(f"{prefix}anchor_count={result.anchor_count}")
    print(f"{prefix}max_negative_score={result.max_negative_score:.6f}")
    print(f"{prefix}max_negative_ids={','.join(result.max_negative_ids)}")
    print(f"{prefix}max_positive_score={result.max_positive_score:.6f}")
    print(f"{prefix}evaluated_candidate_count={result.evaluated_candidate_count}")
    print(f"{prefix}decision={result.decision}")
    print(f"{prefix}recommended_threshold={result.threshold:.6f}")
    print(f"{prefix}recommended_comparison={result.comparison}")
    print(f"{prefix}true_positive_ids={','.join(result.true_positive_ids)}")
    print(f"{prefix}false_positive_ids={','.join(result.false_positive_ids)}")
    print(f"{prefix}false_negative_ids={','.join(result.false_negative_ids)}")
    print(f"{prefix}exempt_negative_ids={','.join(result.exempt_negative_ids)}")
    print(f"{prefix}true_negative_count={result.true_negative_count}")


def main(argv: list[str] | None = None) -> int:
    """摘要：执行校准、自检归档锚并可选写出 JSON 结果。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)

    data = _load_fixture(args.fixture)
    results = calibrate(data)
    print("W3-P2 cross-turn repetition threshold calibration")
    for mode, result in results.items():
        _print_result(args.fixture, mode, result)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(
                {mode: asdict(result) for mode, result in results.items()},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
