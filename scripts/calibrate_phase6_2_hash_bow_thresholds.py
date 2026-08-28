"""摘要：校准 Phase 6.2 hash-bow 语义去重阈值。"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offline_companion.shared.deterministic_embedding import cosine_similarity, embed_text

DEFAULT_FIXTURE = ROOT / "fixtures" / "semantic_event_similarity_pairs.json"
DEFAULT_DIMENSIONS = 768


@dataclass(frozen=True)
class SimilarityStats:
    """摘要：记录一组判别对的余弦相似度分布。"""

    count: int
    min_value: float
    max_value: float
    mean_value: float


def _load_fixture(path: Path) -> dict[str, Any]:
    """摘要：读取并返回校准判别对 fixture。"""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("fixture root must be an object")
    return data


def _score_pairs(pairs: list[dict[str, Any]], *, dimensions: int) -> list[float]:
    """摘要：计算判别对列表的余弦相似度。"""
    scores: list[float] = []
    for pair in pairs:
        left = str(pair["a"])
        right = str(pair["b"])
        scores.append(
            cosine_similarity(
                embed_text(left, dimensions=dimensions),
                embed_text(right, dimensions=dimensions),
            )
        )
    return scores


def _stats(scores: list[float]) -> SimilarityStats:
    """摘要：汇总相似度分布统计值。"""
    if not scores:
        raise ValueError("scores must not be empty")
    return SimilarityStats(
        count=len(scores),
        min_value=min(scores),
        max_value=max(scores),
        mean_value=statistics.fmean(scores),
    )


def _format_stats(label: str, stats: SimilarityStats) -> str:
    """摘要：格式化单组分布，便于文档摘录。"""
    return (
        f"{label}: count={stats.count} min={stats.min_value:.4f} "
        f"max={stats.max_value:.4f} mean={stats.mean_value:.4f}"
    )


def _recommended_threshold(similar: SimilarityStats, dissimilar: SimilarityStats) -> float | None:
    """摘要：在分布分离时给出偏保守的重复阈值。"""
    if similar.min_value <= dissimilar.max_value:
        return None
    gap = similar.min_value - dissimilar.max_value
    return similar.min_value - gap * 0.25


def main(argv: list[str] | None = None) -> int:
    """摘要：执行阈值校准并输出分布与分支判决。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    args = parser.parse_args(argv)

    data = _load_fixture(args.fixture)
    similar_pairs = data.get("similar")
    dissimilar_pairs = data.get("dissimilar")
    if not isinstance(similar_pairs, list) or not isinstance(dissimilar_pairs, list):
        raise ValueError("fixture must contain similar and dissimilar lists")

    similar_stats = _stats(_score_pairs(similar_pairs, dimensions=args.dimensions))
    dissimilar_stats = _stats(_score_pairs(dissimilar_pairs, dimensions=args.dimensions))
    threshold = _recommended_threshold(similar_stats, dissimilar_stats)

    print("Phase 6.2 hash-bow threshold calibration")
    print(f"fixture={args.fixture}")
    print(f"dimensions={args.dimensions}")
    print(_format_stats("similar", similar_stats))
    print(_format_stats("dissimilar", dissimilar_stats))
    if threshold is None:
        print("decision=overlap")
        print("recommendation=downgrade_to_lexical_near_duplicate_or_move_true_embedding_to_v1.7")
        return 0
    related_threshold = max(dissimilar_stats.mean_value, threshold * 0.75)
    print("decision=separable")
    print(f"recommended_duplicate_threshold={threshold:.4f}")
    print(f"recommended_related_threshold={related_threshold:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
