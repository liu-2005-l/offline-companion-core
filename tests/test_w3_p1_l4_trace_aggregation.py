"""摘要：W3-P1 AC-13 逐轮 trace 聚合验收。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.summarize_w3_p1_l4_traces import summarize_l4_records

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    REPO_ROOT / "fixtures" / "persona_constraints" / "w3_p1_l4_trace_aggregation.json"
)


def test_w3_p1_l4_trace_archive_produces_frozen_recalibration_counts() -> None:
    """摘要：逐轮归档必须机械汇总出 AC-13 全部冻结计数。"""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert summarize_l4_records(fixture["records"]) == fixture["expected"]
