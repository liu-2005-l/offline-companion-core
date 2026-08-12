"""desktop：pywebview 桌面壳（Sprint 6.8 · A1 产品宿主）。"""

from __future__ import annotations

__all__ = ["run_desktop"]


def __getattr__(name: str):
    """摘要：延迟导入桌面入口，避免 bootstrap 与桌面子模块形成循环依赖。"""
    if name == "run_desktop":
        from offline_companion.shell.ui_host.desktop.app import run_desktop

        return run_desktop
    raise AttributeError(name)
