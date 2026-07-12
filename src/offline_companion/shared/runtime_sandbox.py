"""runtime_sandbox：运行时危险能力的最小禁用封装。"""

from __future__ import annotations

import builtins
import importlib
import socket
import urllib.request
from contextlib import contextmanager
from typing import Iterator

from offline_companion.shared.errors import SkillInvocationError

_ORIGINAL_SOCKET = socket.socket
_ORIGINAL_URLOPEN = urllib.request.urlopen
_ORIGINAL_IMPORT_MODULE = importlib.import_module
_ORIGINAL_EVAL = builtins.eval
_ORIGINAL_EXEC = builtins.exec
_SANDBOX_ENABLED = False
# TODO(sprint7-close): 目前仅覆盖最小危险能力集合；后续需补充更多运行时边界白名单与子进程级兜底。


def _blocked(*_args, **_kwargs):
    raise SkillInvocationError("当前运行模式禁止使用受限能力")


def enable_runtime_sandbox() -> None:
    """摘要：禁用运行时危险能力的最小兜底实现。"""
    global _SANDBOX_ENABLED
    if _SANDBOX_ENABLED:
        return
    socket.socket = _blocked  # type: ignore[assignment]
    urllib.request.urlopen = _blocked  # type: ignore[assignment]
    importlib.import_module = _blocked  # type: ignore[assignment]
    builtins.eval = _blocked  # type: ignore[assignment]
    builtins.exec = _blocked  # type: ignore[assignment]
    _SANDBOX_ENABLED = True


def disable_runtime_sandbox() -> None:
    """摘要：恢复运行时危险能力，便于测试与本地调试。"""
    global _SANDBOX_ENABLED
    if not _SANDBOX_ENABLED:
        return
    socket.socket = _ORIGINAL_SOCKET  # type: ignore[assignment]
    urllib.request.urlopen = _ORIGINAL_URLOPEN  # type: ignore[assignment]
    importlib.import_module = _ORIGINAL_IMPORT_MODULE  # type: ignore[assignment]
    builtins.eval = _ORIGINAL_EVAL  # type: ignore[assignment]
    builtins.exec = _ORIGINAL_EXEC  # type: ignore[assignment]
    _SANDBOX_ENABLED = False


@contextmanager
def runtime_sandbox() -> Iterator[None]:
    """摘要：以上下文管理器形式临时启用运行时沙箱。"""
    enable_runtime_sandbox()
    try:
        yield
    finally:
        disable_runtime_sandbox()
