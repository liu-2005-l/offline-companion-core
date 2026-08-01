"""runtime_sandbox：运行时危险能力的最小禁用封装。"""

from __future__ import annotations

import builtins
import importlib
import inspect
import socket
import sys
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

from offline_companion.shared.errors import SkillInvocationError

_ORIGINAL_SOCKET = socket.socket
_ORIGINAL_URLOPEN = urllib.request.urlopen
_ORIGINAL_IMPORT_MODULE = importlib.import_module
_ORIGINAL_IMPORT = builtins.__import__
_ORIGINAL_EVAL = builtins.eval
_ORIGINAL_EXEC = builtins.exec
_SANDBOX_ENABLED = False
_ALLOWED_IMPORTS = {
    "math",
    "json",
    "_json",
    "sqlite3",
    "_sqlite3",
    "re",
    "sys",
    "types",
    "abc",
    "datetime",
    "pathlib",
    "typing",
    "dataclasses",
    "enum",
    "functools",
    "itertools",
    "collections",
    "statistics",
    "fractions",
    "decimal",
    "io",
    "_io",
    "_abc",
    "_collections_abc",
    "_datetime",
    "_codecs",
    "codecs",
    "encodings",
    "errno",
    "time",
}
# TODO(sprint7-close): 目前仅覆盖最小危险能力集合；后续需补充更多运行时边界白名单与子进程级兜底。


def _blocked(*_args, **_kwargs):
    raise SkillInvocationError("当前运行模式禁止使用受限能力")




def _safe_eval(*_args, **_kwargs):
    raise SkillInvocationError("?????????????????????")


def _safe_exec(*args, **kwargs):
    for frame_info in inspect.stack()[1:]:
        module_name = str(frame_info.frame.f_globals.get("__name__", ""))
        if module_name.startswith(("importlib", "_frozen_importlib")):
            return _ORIGINAL_EXEC(*args, **kwargs)
    raise SkillInvocationError("?????????????????????")

def _is_allowed_import(name: str) -> bool:
    """摘要：判断模块是否在 Skill 运行时导入白名单中。"""
    root_name = (name or "").split(".", 1)[0]
    return root_name in _ALLOWED_IMPORTS


def _safe_import_module(name: str, *args, **kwargs):
    if _is_allowed_import(name):
        return _ORIGINAL_IMPORT_MODULE(name, *args, **kwargs)
    raise SkillInvocationError(f"当前运行模式禁止动态导入模块: {name}")


def _safe_builtin_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
    if _is_allowed_import(name):
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    if name in {"_io", "_abc", "_collections_abc", "_datetime", "_codecs"}:
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    if name.startswith("_pytest"):
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    # PyInstaller frozen模式下放行bootstrap相关模块
    if getattr(sys, "frozen", False):
        if name in {"PyInstaller", "pkgutil", "importlib", "pkg_resources"}:
            return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
        if name.startswith("_frozen_importlib"):
            return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    if name in sys.builtin_module_names and name not in {"os", "socket", "_socket"}:
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    raise SkillInvocationError(f"当前运行模式禁止导入模块: {name}")


def _safe_socket(*args, **kwargs):
    raise SkillInvocationError("当前运行模式禁止创建网络 socket")


def _safe_urlopen(*args, **kwargs):
    raise SkillInvocationError("当前运行模式禁止发起网络请求")


def enable_runtime_sandbox() -> None:
    """摘要：禁用运行时危险能力的最小兜底实现。"""
    global _SANDBOX_ENABLED
    if _SANDBOX_ENABLED:
        return
    socket.socket = _safe_socket  # type: ignore[assignment]
    urllib.request.urlopen = _safe_urlopen  # type: ignore[assignment]
    importlib.import_module = _safe_import_module  # type: ignore[assignment]
    builtins.__import__ = _safe_builtin_import  # type: ignore[assignment]
    builtins.eval = _safe_eval  # type: ignore[assignment]
    builtins.exec = _safe_exec  # type: ignore[assignment]
    _SANDBOX_ENABLED = True


def disable_runtime_sandbox() -> None:
    """摘要：恢复运行时危险能力，便于测试与本地调试。"""
    global _SANDBOX_ENABLED
    if not _SANDBOX_ENABLED:
        return
    socket.socket = _ORIGINAL_SOCKET  # type: ignore[assignment]
    urllib.request.urlopen = _ORIGINAL_URLOPEN  # type: ignore[assignment]
    importlib.import_module = _ORIGINAL_IMPORT_MODULE  # type: ignore[assignment]
    builtins.__import__ = _ORIGINAL_IMPORT  # type: ignore[assignment]
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
