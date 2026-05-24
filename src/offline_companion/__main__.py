"""允许 ``python -m offline_companion`` 或 PyInstaller 便携包启动 CLI。"""

from __future__ import annotations

import sys

from offline_companion.shell.ui_host.portable_runtime import bootstrap_if_frozen


def _argv_for_entry() -> list[str]:
    """摘要：便携 exe 无参数时默认进入 ``chat`` 子命令。"""
    rest = sys.argv[1:]
    if not rest and getattr(sys, "frozen", False):
        return ["chat"]
    return rest


if __name__ == "__main__":
    bootstrap_if_frozen()
    from offline_companion.shell.ui_host.cli import main

    main(_argv_for_entry())
