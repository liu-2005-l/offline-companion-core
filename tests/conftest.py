"""pytest 共享 fixture 与跨平台测试辅助。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def patch_platform_user_data_home(monkeypatch: pytest.MonkeyPatch, user_base: Path) -> None:
    """摘要：按 OS 注入用户数据根父目录（与 ``data_root()`` 一致）。

    Windows 用 ``LOCALAPPDATA``；Linux/macOS 用 ``XDG_DATA_HOME``。
    勿在跨平台测试中只设置 ``LOCALAPPDATA``。
    """
    monkeypatch.delenv("OFFLINE_COMPANION_DATA_DIR", raising=False)
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(user_base))
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(user_base))
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
