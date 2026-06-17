"""摘要：回归 fixture 数量与分类（Sprint 4.4）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "regression_dialogues.yaml"
STATS = ROOT / "scripts" / "ci" / "fixture_stats.py"


def _load_cases() -> list[dict]:
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def test_fixture_executable_count_at_least_80() -> None:
    r = subprocess.run(
        [sys.executable, str(STATS), "--min-executable", "80"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_fixture_executable_count_at_least_50() -> None:
    """摘要：保留 50 下限子集检查（向后兼容）。"""
    r = subprocess.run(
        [sys.executable, str(STATS), "--min-executable", "50"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_fixture_has_kind_or_inferable() -> None:
    cases = _load_cases()
    assert len(cases) >= 80
    explicit = sum(1 for c in cases if c.get("kind") in ("executable", "note"))
    assert explicit >= 10
