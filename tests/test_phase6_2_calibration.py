"""摘要：Phase 6.2 hash-bow 阈值校准资产测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from offline_companion.core.memory_lifecycle.event_extractor import HASH_BOW_DUPLICATE_THRESHOLD
from offline_companion.shared.deterministic_embedding import cosine_similarity, embed_text


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "semantic_event_similarity_pairs.json"
SCRIPT = ROOT / "scripts" / "calibrate_phase6_2_hash_bow_thresholds.py"


def test_phase6_2_similarity_fixture_shape() -> None:
    """摘要：校准判别对保持 40/40 规模与同义改写覆盖率。"""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    similar = data["similar"]
    dissimilar = data["dissimilar"]
    literal_edits = [pair for pair in similar if pair.get("pair_type") == "literal_edit"]
    paraphrases = [pair for pair in similar if pair.get("pair_type") == "paraphrase"]

    assert len(similar) == 40
    assert len(dissimilar) == 40
    assert len(paraphrases) >= 12
    assert len(literal_edits) >= 8
    assert all(pair.get("pair_type") == "dissimilar" for pair in dissimilar)
    assert all(pair.get("a") and pair.get("b") for pair in similar + dissimilar)


def test_phase6_2_calibration_script_runs_without_model() -> None:
    """摘要：校准脚本只依赖确定性 hash-bow，不加载模型文件。"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Phase 6.2 hash-bow threshold calibration" in result.stdout
    assert "all_similar: count=40" in result.stdout
    assert "all_dissimilar: count=40" in result.stdout
    assert "literal_edit: count=" in result.stdout
    assert "paraphrase: count=" in result.stdout
    assert "decision=" in result.stdout
    assert "hash_bow_duplicate_threshold=0.50" in result.stdout
    assert "hash_bow_related_threshold=not_implemented" in result.stdout


def test_phase6_2_hash_bow_threshold_separates_literal_edits_only() -> None:
    """摘要：0.50 阈值只承诺字面近似去重，不承诺同义改写去重。"""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scores_by_type: dict[str, list[float]] = {"literal_edit": [], "paraphrase": [], "dissimilar": []}
    for pair in data["similar"] + data["dissimilar"]:
        score = cosine_similarity(
            embed_text(pair["a"], dimensions=768),
            embed_text(pair["b"], dimensions=768),
        )
        scores_by_type[pair["pair_type"]].append(score)

    assert min(scores_by_type["literal_edit"]) >= HASH_BOW_DUPLICATE_THRESHOLD
    assert max(scores_by_type["paraphrase"]) < HASH_BOW_DUPLICATE_THRESHOLD
    assert max(scores_by_type["dissimilar"]) < HASH_BOW_DUPLICATE_THRESHOLD
