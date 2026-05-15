"""rules：路径解析与隐私相关内置规则（A2）。"""

from __future__ import annotations

import os
from pathlib import Path

from offline_companion.shared.types import AppPaths


def default_data_root() -> Path:
    """摘要：解析操作系统用户数据根目录。"""
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA")
        if la:
            return Path(la)
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def default_app_paths() -> AppPaths:
    """摘要：构造默认应用数据路径（含数据库与导出目录）。"""
    base = default_data_root() / "OfflineCompanion"
    base.mkdir(parents=True, exist_ok=True)
    personas = base / "personas"
    personas.mkdir(parents=True, exist_ok=True)
    exports = base / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    return AppPaths(root=base, db_path=base / "companion.db", personas_dir=personas, exports_dir=exports)
