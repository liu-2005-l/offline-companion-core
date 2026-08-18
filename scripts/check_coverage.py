"""摘要：运行测试并执行按目录划分的覆盖率门禁。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

THRESHOLDS = {
    "src/offline_companion/core/": 70.0,
    "src/offline_companion/runtime/": 65.0,
    "src/offline_companion/shell/": 60.0,
    "overall": 65.0,
}


def _coverage_value(files: dict[str, dict], prefix: str) -> float | None:
    selected = [item["summary"] for name, item in files.items() if name.replace("\\", "/").startswith(prefix)]
    if not selected:
        return None
    covered = sum(item["covered_lines"] for item in selected)
    statements = sum(item["num_statements"] for item in selected)
    return covered / statements * 100 if statements else 100.0


def check(*, coverage_file: Path = Path("coverage.json")) -> int:
    """摘要：读取 coverage.py JSON 报告并返回门禁退出码。"""
    if not coverage_file.is_file():
        print(f"Coverage report missing: {coverage_file}")
        return 2
    report = json.loads(coverage_file.read_text(encoding="utf-8"))
    files = report.get("files", {})
    failures: list[str] = []
    for prefix, threshold in THRESHOLDS.items():
        actual = report["totals"]["percent_covered"] if prefix == "overall" else _coverage_value(files, prefix)
        if actual is not None and actual < threshold:
            failures.append(f"{prefix}: {actual:.1f}% < {threshold:.1f}%")
    if failures:
        print("Coverage check FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("Coverage check PASSED")
    return 0


def main() -> int:
    """摘要：生成覆盖率报告并执行门禁。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--cov=src", "--cov-report=json", "--cov-report=term", "-q"],
        check=False,
    )
    if result.returncode:
        return result.returncode
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
