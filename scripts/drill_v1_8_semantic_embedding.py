"""运行 v1.8.0 V1-C 真 semantic embedding 翻转与阈值重校 drill。"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offline_companion.core.memory_lifecycle.event_recaller import (
    HASH_BOW_RECALL_THRESHOLD,
    SEMANTIC_RECALL_THRESHOLD,
    EventRecaller,
)
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import SemanticEvent
from offline_companion.core.memory_lifecycle.semantic_embedding_provider import (
    SemanticEmbeddingProvider,
    embedding_space_of,
)
from offline_companion.shared.deterministic_embedding import cosine_similarity

TRIPWIRES = (
    ("R43", "canine companion naps beside keyboard", "dog sleeps near laptop"),
    ("R44", "relocate shanghai next spring", "move magiccity after winter"),
    ("R45", "cilantro causes nausea", "avoid coriander garnish"),
    ("R46", "offline default privacy policy", "network access requires consent"),
)
FIXTURE = ROOT / "fixtures" / "semantic_event_similarity_pairs.json"


def main() -> int:
    """摘要：输出 C2 两阶段前半段所需的模型贡献表与重校分布。"""
    provider = SemanticEmbeddingProvider()
    report = {
        "embedding_space": provider.preferred_embedding_space,
        "query_prefix": "off",
        "threshold_unchanged": HASH_BOW_RECALL_THRESHOLD,
        "semantic_recall_threshold": SEMANTIC_RECALL_THRESHOLD,
        "tripwires": _tripwire_rows(provider),
        "distributions": _fixture_distributions(provider),
        "threshold_sweep": _threshold_sweep(provider),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _tripwire_rows(provider: SemanticEmbeddingProvider) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case_id, content, query in TRIPWIRES:
        conn = sqlite3.connect(":memory:")
        repo = EventRepository(conn)
        content_embedding = provider(content)
        repo.store(
            SemanticEvent(
                event_id=case_id,
                event_type="fact",
                subject="user",
                content=content,
                content_embedding=content_embedding,
                content_embedding_space=embedding_space_of(provider),
                importance=4.0,
                created_at=1.0,
            )
        )
        query_embedding = provider(query)
        distance = repo.vector_search(
            query_embedding,
            top_k=1,
            embedding_space=embedding_space_of(provider),
        )[0][1]
        results = EventRecaller(repo, embed_func=provider).recall(query, top_k=5)
        rows.append(
            {
                "case_id": case_id,
                "similarity": round(1.0 - distance, 6),
                "result_ids": [event.event_id for event in results],
                "status": "correct" if results else "degraded",
            }
        )
    return rows


def _fixture_distributions(provider: SemanticEmbeddingProvider) -> dict[str, dict[str, float]]:
    scores_by_type = _fixture_scores(provider)
    return {
        pair_type: {
            "count": len(scores),
            "min": round(min(scores), 6),
            "max": round(max(scores), 6),
            "mean": round(statistics.fmean(scores), 6),
        }
        for pair_type, scores in sorted(scores_by_type.items())
    }


def _threshold_sweep(provider: SemanticEmbeddingProvider) -> list[dict[str, object]]:
    scores_by_type = _fixture_scores(provider)
    thresholds = (0.50, 0.55, 0.575, 0.58, 0.60, 0.65, 0.70, 0.75, 0.80)
    return [
        {
            "threshold": threshold,
            "literal_hit": _count_at(scores_by_type.get("literal_edit", []), threshold),
            "paraphrase_hit": _count_at(scores_by_type.get("paraphrase", []), threshold),
            "dissimilar_false_positive": _count_at(scores_by_type.get("dissimilar", []), threshold),
        }
        for threshold in thresholds
    ]


def _fixture_scores(provider: SemanticEmbeddingProvider) -> dict[str, list[float]]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scores_by_type: dict[str, list[float]] = {}
    for group in ("similar", "dissimilar"):
        for pair in fixture[group]:
            pair_type = str(pair.get("pair_type") or group)
            left = provider(str(pair["a"]))
            right = provider(str(pair["b"]))
            scores_by_type.setdefault(pair_type, []).append(cosine_similarity(left, right))
    return scores_by_type


def _count_at(scores: list[float], threshold: float) -> str:
    return f"{sum(score >= threshold for score in scores)}/{len(scores)}"


if __name__ == "__main__":
    raise SystemExit(main())
