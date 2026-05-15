"""companion：旧根包名兼容层（非正式分发；将在未来大版本移除）。"""

from __future__ import annotations

import warnings

warnings.warn(
    "根包 `companion` 已弃用，请改用 `offline_companion`（例如 `from offline_companion.shell.ui_host.cli import main`）。",
    DeprecationWarning,
    stacklevel=2,
)

__all__: list[str] = []
