"""摘要：Phase 6.2 hash-bow 阈值校准资产测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "semantic_event_similarity_pairs.json"
SCRIPT = ROOT / "scripts" / "calibrate_phase6_2_hash_bow_thresholds.py"


def test_phase6_2_similarity_fixture_shape() -> None:
    """摘要：校准判别对保持 40/40 规模与同义改写覆盖率。"""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    similar = data["similar"]
    dissimilar = data["dissimilar"]
    paraphrases = [pair for pair in similar if pair.get("kind") == "paraphrase"]

    assert len(similar) == 40
    assert len(dissimilar) == 40
    assert len(paraphrases) >= 12
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
    assert "similar: count=40" in result.stdout
    assert "dissimilar: count=40" in result.stdout
    assert "decision=" in result.stdout
