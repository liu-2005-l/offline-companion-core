"""摘要：桌面应用本地崩溃日志、运行 sentinel 与待处理报告管理。"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

_RUNNING_SENTINEL = ".app_running"


@dataclass(frozen=True)
class PendingCrashReport:
    """摘要：上次异常退出留下的待处理崩溃报告。"""

    path: Path
    content: str


@dataclass
class CrashHandlerInstallation:
    """摘要：保存异常钩子原值，供测试或嵌入场景恢复。"""

    original_sys_hook: Any
    original_thread_hook: Any
    loop: asyncio.AbstractEventLoop | None = None
    original_loop_handler: Any = None

    def restore(self) -> None:
        """摘要：恢复安装前的主线程、子线程与 asyncio 异常钩子。"""
        sys.excepthook = self.original_sys_hook
        threading.excepthook = self.original_thread_hook
        if self.loop is not None and not self.loop.is_closed():
            self.loop.set_exception_handler(self.original_loop_handler)


def write_crash_report(
    data_root: Path,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
    *,
    source: str,
) -> Path:
    """摘要：将异常详情写入本地 crashes 目录。

    参数：
        data_root: 应用数据根目录。
        exc_type: 异常类型。
        exc_value: 异常实例。
        exc_traceback: 异常 traceback。
        source: 异常来源标识。

    返回值：
        新建的崩溃日志路径。
    """
    crash_dir = data_root / "crashes"
    crash_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    crash_path = crash_dir / f"crash_{timestamp}_{uuid.uuid4().hex[:8]}.log"
    content = "".join(
        [
            "Offline Companion Crash Report\n",
            f"Timestamp: {timestamp}\n",
            f"Source: {source}\n",
            f"Exception: {exc_type.__name__}: {exc_value}\n",
            "\nTraceback:\n",
            "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
        ]
    )
    crash_path.write_text(content, encoding="utf-8")
    return crash_path


def setup_crash_handler(data_root: Path) -> CrashHandlerInstallation:
    """摘要：安装本地异常钩子并返回可恢复的安装句柄。"""
    original_sys_hook = sys.excepthook
    original_thread_hook = threading.excepthook

    def sys_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            _safe_write_report(data_root, exc_type, exc_value, exc_traceback, source="main_thread")
        original_sys_hook(exc_type, exc_value, exc_traceback)

    def thread_hook(args: Any) -> None:
        _safe_write_report(
            data_root,
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            source=f"thread:{getattr(args.thread, 'name', 'unknown')}",
        )
        original_thread_hook(args)

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return CrashHandlerInstallation(original_sys_hook, original_thread_hook)
    original_loop_handler = loop.get_exception_handler()

    def loop_exception_handler(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exception = context.get("exception")
        if isinstance(exception, BaseException):
            _safe_write_report(
                data_root,
                type(exception),
                exception,
                exception.__traceback__,
                source="asyncio",
            )
        if original_loop_handler is not None:
            original_loop_handler(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    loop.set_exception_handler(loop_exception_handler)
    return CrashHandlerInstallation(
        original_sys_hook,
        original_thread_hook,
        loop,
        original_loop_handler,
    )


def mark_app_started(data_root: Path) -> None:
    """摘要：写入本次启动 sentinel，供下次判断是否异常退出。"""
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / _RUNNING_SENTINEL).write_text(str(time.time()), encoding="utf-8")


def mark_app_stopped(data_root: Path) -> None:
    """摘要：正常退出时删除运行 sentinel。"""
    (data_root / _RUNNING_SENTINEL).unlink(missing_ok=True)


def check_previous_crash(data_root: Path) -> PendingCrashReport | None:
    """摘要：检测上次运行期间生成且尚未归档的最新崩溃日志。"""
    sentinel = data_root / _RUNNING_SENTINEL
    if not sentinel.is_file():
        return None
    try:
        started_at = float(sentinel.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        started_at = sentinel.stat().st_mtime
    crash_dir = data_root / "crashes"
    crashes = sorted(crash_dir.glob("crash_*.log"), key=lambda path: path.stat().st_mtime)
    eligible = [path for path in crashes if path.stat().st_mtime >= started_at]
    if not eligible:
        return None
    latest = eligible[-1]
    try:
        content = latest.read_text(encoding="utf-8")
    except OSError:
        return None
    return PendingCrashReport(path=latest, content=content)


def archive_crash_report(data_root: Path, crash_path: Path, *, category: str) -> Path:
    """摘要：将待处理崩溃日志移入 archived 或 submitted 子目录。"""
    crash_dir = (data_root / "crashes").resolve()
    resolved_path = crash_path.resolve()
    if resolved_path.parent != crash_dir or not resolved_path.is_file():
        raise ValueError("invalid_crash_report_path")
    target_dir = crash_dir / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / resolved_path.name
    if target.exists():
        target = target_dir / f"{resolved_path.stem}_{uuid.uuid4().hex[:8]}{resolved_path.suffix}"
    os.replace(str(resolved_path), str(target))
    return target


def _safe_write_report(
    data_root: Path,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
    *,
    source: str,
) -> None:
    try:
        write_crash_report(
            data_root,
            exc_type,
            exc_value,
            exc_traceback,
            source=source,
        )
    except OSError:
        return
