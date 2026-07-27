"""file_read_tool：受限本地只读 Tool。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.shared.runtime_paths import data_root, dev_repo_root


def file_read(path: str) -> dict[str, object]:
    """摘要：读取白名单根目录内的 UTF-8 文本文件。"""
    resolved = Path(path).expanduser().resolve(strict=True)
    _ensure_allowed_path(resolved)
    if not resolved.is_file():
        raise ValueError("path must point to a file")
    return {
        "path": str(resolved),
        "content": resolved.read_text(encoding="utf-8"),
    }


def _ensure_allowed_path(path: Path) -> None:
    """摘要：确保目标路径位于允许的只读根目录内。"""
    allowed_roots = (
        dev_repo_root().resolve(),
        data_root().resolve(),
    )
    if any(_is_relative_to(path, root) for root in allowed_roots):
        return
    raise ValueError("path is outside allowed read-only roots")


def _is_relative_to(path: Path, root: Path) -> bool:
    """摘要：兼容旧版 Python 的路径包含判断。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
