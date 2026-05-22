#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：统计 regression_dialogues.yaml 中 executable / note 数量。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "regression_dialogues.yaml"

_AUTOMATED_CATEGORIES = frozenset(
    {
        "safety",
        "memory",
        "memory_recall",
        "memory_lifecycle",
        "memory_draft",
        "orchestrator",
        "knowledge",
    }
)


def infer_kind(case: dict) -> str:
    """摘要：推断用例种类；显式 kind 优先。"""
    if case.get("kind") in ("executable", "note"):
        return str(case["kind"])
    if case.get("note") and not any(str(k).startswith("expect") for k in case):
        return "note"
    if case.get("category") in _AUTOMATED_CATEGORIES and any(
        str(k).startswith("expect") for k in case
    ):
        return "executable"
    if case.get("category") in ("orchestrator", "knowledge", "memory_draft"):
        return "executable"
    return "note"


def load_cases() -> list[dict]:
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def main() -> int:
    """摘要：打印 fixture 统计；``--min-executable`` 不满足时退出 1。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-executable", type=int, default=0)
    args = parser.parse_args()
    cases = load_cases()
    exe = [c for c in cases if infer_kind(c) == "executable"]
    notes = [c for c in cases if infer_kind(c) == "note"]
    print(f"fixture: {FIXTURE.name}")
    print(f"  total cases: {len(cases)}")
    print(f"  executable (inferred): {len(exe)}")
    print(f"  note (inferred): {len(notes)}")
    by_cat: dict[str, int] = {}
    for c in exe:
        cat = str(c.get("category") or "unknown")
        by_cat[cat] = by_cat.get(cat, 0) + 1
    if by_cat:
        print("  executable by category:")
        for cat, n in sorted(by_cat.items()):
            print(f"    {cat}: {n}")
    if args.min_executable and len(exe) < args.min_executable:
        print(f"[FAIL] executable {len(exe)} < {args.min_executable}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
