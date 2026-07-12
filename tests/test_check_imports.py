"""check_imports 最小测试。"""

from __future__ import annotations

from scripts.ci.check_imports import main


def test_check_imports_passes() -> None:
    """当前仓库应通过最小危险导入检查。"""
    assert main() == 0
