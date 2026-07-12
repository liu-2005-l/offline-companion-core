#!/usr/bin/env python3
"""摘要：AST 级依赖与网络导入硬约束（违反即非零退出）。"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2] / "src" / "offline_companion"
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from offline_companion.shared.errors import CheckImportsError
NET_MODULES = ("httpx", "requests", "urllib3", "socket", "aiohttp")
GUI_MODULES = ("pywebview", "pystray", "PIL")
SKILL_DEPS = ("packaging", "jsonschema")
ALLOW_NET_FILE = Path("offline_companion/shell/outbound_manager/connector.py")
ALLOW_GUI_PREFIX = "offline_companion/shell/ui_host/desktop/"
ALLOW_NET_PREFIXES = (
    "offline_companion/shell/outbound_manager/",
    "offline_companion/shell/skill_manager/",
)
ALLOW_NET_FILES = {
    Path("offline_companion/shared/runtime_sandbox.py"),
}
# TODO(sprint7-close): 目前仅做 AST 级最小检查；后续需补充更细粒度的层级白名单与测试覆盖。


def _rel_posix(path: Path) -> str:
    return path.relative_to(ROOT.parent).as_posix()


def path_matches(rel: str, paths: set[Path]) -> bool:
    return any(rel == p.as_posix() for p in paths)


def _collect_imports(tree: ast.AST) -> list[tuple[str, str]]:
    """返回 (kind, module) 列表；module 可能为顶级包名或 from 前缀。"""
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(("import", alias.name.split(".")[0]))
                out.append(("import_full", alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(("from", node.module))
                out.append(("from_root", node.module.split(".")[0]))
    return out


def _violates_network(rel: str, tree: ast.AST) -> list[str]:
    if rel == ALLOW_NET_FILE.as_posix() or rel.startswith(ALLOW_GUI_PREFIX):
        return []
    if path_matches(rel, ALLOW_NET_FILES):
        return []
    if any(rel.startswith(p) for p in ALLOW_NET_PREFIXES):
        return []
    bad: list[str] = []

    for kind, mod in _collect_imports(tree):
        if kind in {"import", "from_root"} and mod in NET_MODULES:
            bad.append(f"{rel}: forbidden network module `{mod}`")
        if kind == "from" and mod.split(".")[0] in NET_MODULES:
            bad.append(f"{rel}: forbidden network import `{mod}`")
    return bad


def _violates_gui(rel: str, tree: ast.AST) -> list[str]:
    if rel.startswith(ALLOW_GUI_PREFIX):
        return []
    if not (rel.startswith("offline_companion/core/") or rel.startswith("offline_companion/runtime/")):
        return []
    bad: list[str] = []
    for kind, mod in _collect_imports(tree):
        if kind in {"import", "from_root"} and mod in GUI_MODULES:
            bad.append(f"{rel}: forbidden GUI module `{mod}`")
        if kind == "from" and mod and mod.split(".")[0] in GUI_MODULES:
            bad.append(f"{rel}: forbidden GUI import `{mod}`")
    return bad


def _violates_skill_deps(rel: str, tree: ast.AST) -> list[str]:
    """B/C 禁止 import skill_manager 及其可选依赖 packaging/jsonschema。"""
    if not (
        rel.startswith("offline_companion/core/")
        or rel.startswith("offline_companion/runtime/")
    ):
        return []
    bad: list[str] = []
    for kind, mod in _collect_imports(tree):
        if kind in {"import", "from_root"} and mod in SKILL_DEPS:
            bad.append(f"{rel}: forbidden skill optional dependency `{mod}`")
        if kind == "from" and mod and mod.split(".")[0] in SKILL_DEPS:
            bad.append(f"{rel}: forbidden skill optional import `{mod}`")
    return bad


def _violates_layers(rel: str, tree: ast.AST) -> list[str]:
    bad: list[str] = []
    imports = _collect_imports(tree)
    for kind, mod in imports:
        if kind == "import_full" and mod.startswith("offline_companion."):
            full = mod
        elif kind == "from" and mod.startswith("offline_companion."):
            full = mod
        else:
            continue
        if rel.startswith("offline_companion/core/") and full.startswith("offline_companion.shell"):
            bad.append(f"{rel}: core must not import shell ({full})")
        if rel.startswith("offline_companion/runtime/") and full.startswith(
            ("offline_companion.shell", "offline_companion.core")
        ):
            bad.append(f"{rel}: runtime must not import shell/core ({full})")
        if rel.startswith("offline_companion/core/") and "skill_manager" in full:
            bad.append(f"{rel}: core must not import skill_manager ({full})")
        if rel.startswith("offline_companion/runtime/") and "skill_manager" in full:
            bad.append(f"{rel}: runtime must not import skill_manager ({full})")
        if rel.startswith("offline_companion/shell/policy_engine/") and full.startswith(
            "offline_companion.runtime"
        ):
            bad.append(f"{rel}: policy_engine must not import runtime ({full})")
    return bad


def main() -> int:
    errors: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = _rel_posix(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:
            errors.append(f"{rel}: syntax error {e}")
            continue
        errors.extend(_violates_network(rel, tree))
        errors.extend(_violates_gui(rel, tree))
        errors.extend(_violates_skill_deps(rel, tree))
        errors.extend(_violates_layers(rel, tree))

    if errors:
        raise CheckImportsError("\n".join(errors))
    print("check_imports OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
