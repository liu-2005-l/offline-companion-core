"""覆盖率门禁脚本测试。"""

from __future__ import annotations

import json

from scripts.check_coverage import check


def _report(path, percent: float) -> None:
    path.write_text(
        json.dumps(
            {
                "totals": {"percent_covered": percent},
                "files": {
                    "src/offline_companion/core/sample.py": {
                        "summary": {"covered_lines": percent, "num_statements": 100}
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_coverage_gate_passes_threshold(tmp_path) -> None:
    report = tmp_path / "coverage.json"
    _report(report, 80)
    assert check(coverage_file=report) == 0


def test_coverage_gate_fails_threshold(tmp_path) -> None:
    report = tmp_path / "coverage.json"
    _report(report, 10)
    assert check(coverage_file=report) == 1


def test_coverage_gate_missing_report(tmp_path) -> None:
    assert check(coverage_file=tmp_path / "missing.json") == 2
