#!/usr/bin/env python3
"""????? B ? prompt/????????? Skill ?????"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ForbiddenKeyword:
    """???????????? B ? prompt ????????"""

    value: str
    source: str


DEFAULT_SCAN_TARGETS = (
    Path("src/offline_companion/core"),
    Path("configs/personas"),
    Path("configs/safety_replies"),
)
_ALLOWED_SUFFIXES = {".py", ".yaml", ".yml", ".txt", ".md"}


def build_parser() -> argparse.ArgumentParser:
    """??????????????"""
    parser = argparse.ArgumentParser(description="?? B ? prompt ???? Skill ????")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="????????????",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="???????????????????????????",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="?????????????????????????",
    )
    return parser


def _ensure_src_on_sys_path(root: Path) -> None:
    """摘要：脚本直接执行时显式把 ``src/`` 加入 ``sys.path``。"""
    src_root = root / "src"
    src_text = str(src_root)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)


def compile_patterns(keywords: list[ForbiddenKeyword]) -> list[tuple[ForbiddenKeyword, re.Pattern[str]]]:
    """?????????????????????????"""
    compiled: list[tuple[ForbiddenKeyword, re.Pattern[str]]] = []
    for keyword in keywords:
        pattern = re.compile(rf"(?i)(?<!\w){re.escape(keyword.value)}(?!\w)")
        compiled.append((keyword, pattern))
    return compiled


def gather_targets(root: Path, extra_targets: list[str]) -> list[Path]:
    """???????????????"""
    raw_targets = [root / item for item in extra_targets] if extra_targets else [root / item for item in DEFAULT_SCAN_TARGETS]
    files: list[Path] = []
    for target in raw_targets:
        if not target.exists():
            continue
        if target.is_file():
            if target.suffix.lower() in _ALLOWED_SUFFIXES:
                files.append(target)
            continue
        for path in sorted(target.rglob("*")):
            if path.is_file() and path.suffix.lower() in _ALLOWED_SUFFIXES:
                files.append(path)
    return files


def default_keywords(root: Path, extra_keywords: list[str]) -> list[ForbiddenKeyword]:
    """摘要：返回默认目录中的自动生成关键词，再叠加 CLI 显式输入。"""
    _ensure_src_on_sys_path(root)
    from offline_companion.shell.skill_manager.capability_catalog import build_capability_keywords

    keywords = [
        ForbiddenKeyword(keyword.value, keyword.source)
        for keyword in build_capability_keywords(root)
    ]
    for item in extra_keywords:
        text = (item or "").strip()
        if text:
            keywords.append(ForbiddenKeyword(text, "cli"))
    unique: dict[str, ForbiddenKeyword] = {}
    for keyword in keywords:
        unique.setdefault(keyword.value.lower(), keyword)
    return list(unique.values())


def scan_file(path: Path, root: Path, patterns: list[tuple[ForbiddenKeyword, re.Pattern[str]]]) -> list[str]:
    """?????????????????"""
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(root).as_posix()
    errors: list[str] = []
    for keyword, pattern in patterns:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            errors.append(
                f"{rel}:{line}: forbidden prompt keyword {keyword.value!r} (source={keyword.source})"
            )
    return errors


def run_scan(root: Path, *, targets: list[str] | None = None, extra_keywords: list[str] | None = None) -> list[str]:
    """????? prompt ????????????"""
    target_files = gather_targets(root, list(targets or []))
    patterns = compile_patterns(default_keywords(root, list(extra_keywords or [])))
    errors: list[str] = []
    for path in target_files:
        errors.extend(scan_file(path, root, patterns))
    return errors


def main(argv: list[str] | None = None) -> int:
    """?????????????????????"""
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors = run_scan(root, targets=args.target, extra_keywords=args.keyword)
    if errors:
        print("\n".join(errors))
        return 1
    print("check_prompt_decoupling OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
