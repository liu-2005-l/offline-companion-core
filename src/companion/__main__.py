"""兼容 `python -m companion`（弃用）。"""

from __future__ import annotations

import warnings

from offline_companion.shell.ui_host.cli import main

warnings.warn(
    "`python -m companion` 已弃用，请改用 `python -m offline_companion`。",
    DeprecationWarning,
    stacklevel=2,
)

if __name__ == "__main__":
    main()
