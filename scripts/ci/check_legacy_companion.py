#!/usr/bin/env python3
"""摘要：扫描仓库，禁止残留 `import companion` / `from companion`（`src/companion` 兼容层除外）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERN = re.compile(r"^\s*(?:from\s+companion\b|import\s+companion\b)", re.MULTILINE)
ALLOW_DIR = (ROOT / "src" / "companion").resolve()


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent)
        return True
    except ValueError:
        return False


def main() -> int:
    bad: list[str] = []
    pyproject = ROOT / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        if "companion.cli" in text:
            bad.append(f"{pyproject}: legacy console script still references companion.cli")

    for base in (ROOT / "src", ROOT / "tests", ROOT / "scripts"):
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if _is_under(path, ALLOW_DIR):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if PATTERN.search(content):
                bad.append(f"{path}: legacy companion import")

    if bad:
        print("Legacy companion import check FAILED:\n" + "\n".join(bad), file=sys.stderr)
        return 1
    print("Legacy companion import check OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
