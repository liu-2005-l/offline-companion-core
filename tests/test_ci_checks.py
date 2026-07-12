"""CI 检查脚本最小测试。"""

from __future__ import annotations

from scripts.ci.check_imports import main


def test_check_imports_script_passes() -> None:
    """仓库当前代码应通过 AST 分层检查。"""
    assert main() == 0
