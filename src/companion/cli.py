"""兼容旧入口 `companion.cli:main`（弃用）。"""

from __future__ import annotations

import warnings

from offline_companion.shell.ui_host.cli import build_parser, cmd_chat, main

warnings.warn(
    "`companion.cli` 已弃用，请改用 `offline_companion.shell.ui_host.cli`。",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["main", "cmd_chat", "build_parser"]
