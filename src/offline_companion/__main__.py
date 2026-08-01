"""允许 ``python -m offline_companion`` 或 PyInstaller 便携包启动 CLI。"""

from __future__ import annotations

import ctypes
import datetime as _dt
import logging
import os
import platform
import sys
import traceback
from pathlib import Path

from offline_companion.shell.ui_host.portable_runtime import bootstrap_if_frozen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)


def _crash_log_dir() -> Path:
    """摘要：返回未捕获异常日志目录。"""
    try:
        from offline_companion.shared.runtime_paths import data_root

        root = data_root()
    except (ImportError, OSError, RuntimeError):
        root = Path.cwd() / "data"
    path = root / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _show_crash_message(path: Path) -> None:
    """摘要：尽力向桌面用户展示崩溃日志位置。"""
    if not (getattr(sys, "frozen", False) or sys.argv[1:2] == ["desktop"]):
        return
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"程序遇到未处理异常，日志已保存到：\n{path}",
            "Offline Companion 遇到问题",
            0x10,
        )
    except (AttributeError, OSError):
        return


def _excepthook(exc_type, exc_value, exc_traceback) -> None:
    """摘要：记录未捕获异常并保持默认异常输出。"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    now = _dt.datetime.now(_dt.timezone.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    log_path = _crash_log_dir() / f"crash_{timestamp}.log"
    lines = [
        f"time={now.isoformat(timespec='seconds')}\n",
        f"python={sys.version}\n",
        f"platform={platform.platform()}\n",
        f"executable={sys.executable}\n",
        f"argv={sys.argv!r}\n\n",
        "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
    ]
    try:
        log_path.write_text("".join(lines), encoding="utf-8")
    except OSError:
        logging.getLogger(__name__).exception("未能写入崩溃日志")
    sys.__excepthook__(exc_type, exc_value, exc_traceback)
    _show_crash_message(log_path)


sys.excepthook = _excepthook


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
