"""摘要：Skill 子进程 Python 层运行时沙箱。"""

from __future__ import annotations

import builtins
import importlib
import ipaddress
import socket
import sys
import types
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from offline_companion.shared.errors import SkillInvocationError

_ORIGINAL_SOCKET = socket.socket
_ORIGINAL_URLOPEN = urllib.request.urlopen
_ORIGINAL_IMPORT_MODULE = importlib.import_module
_ORIGINAL_IMPORT = builtins.__import__
_ORIGINAL_EVAL = builtins.eval
_ORIGINAL_EXEC = builtins.exec
_SANDBOX_ENABLED = False
_ACTIVE_SANDBOX: RuntimeSandbox | None = None
_NETWORK_MODULES = ("requests", "httpx", "urllib3", "aiohttp")
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
    "os",
    "pkgutil",
    "time",
    "socket",
    "_socket",
    "http",
    "socketserver",
    "threading",
    "base64",
    "binascii",
    "email",
    "html",
    "importlib",
}


class _NetworkDisabledModule(types.ModuleType):
    """摘要：网络模块占位符，任何属性访问都会失败。"""

    def __getattr__(self, name: str) -> object:
        """摘要：阻断网络模块能力访问。"""
        raise SkillInvocationError(f"Skill 未声明网络权限，禁止访问模块 {self.__name__}.{name}")


class RuntimeSandbox:
    """摘要：运行时危险能力拦截器。"""

    def __init__(self, *, allow_local_socket: bool = False, blocked_modules: tuple[str, ...] = _NETWORK_MODULES) -> None:
        """摘要：创建运行时沙箱。

        参数：
            allow_local_socket: 是否允许本地地址 socket，用于 local_api Skill 回调宿主。
            blocked_modules: 需要在导入层替换为禁用 stub 的网络模块。
        """
        self.allow_local_socket = allow_local_socket
        self.blocked_modules = blocked_modules
        self._saved_modules: dict[str, types.ModuleType | None] = {}
        self._applied = False

    def apply(self) -> None:
        """摘要：启用运行时危险能力拦截。"""
        global _ACTIVE_SANDBOX, _SANDBOX_ENABLED
        if self._applied:
            return
        socket.socket = _GuardedSocket if self.allow_local_socket else _safe_socket  # type: ignore[assignment]
        urllib.request.urlopen = _safe_urlopen  # type: ignore[assignment]
        importlib.import_module = _safe_import_module  # type: ignore[assignment]
        builtins.__import__ = _safe_builtin_import  # type: ignore[assignment]
        builtins.eval = _safe_eval  # type: ignore[assignment]
        builtins.exec = _safe_exec  # type: ignore[assignment]
        for module_name in self.blocked_modules:
            self._saved_modules[module_name] = sys.modules.get(module_name)
            sys.modules[module_name] = _NetworkDisabledModule(module_name)
        _ACTIVE_SANDBOX = self
        _SANDBOX_ENABLED = True
        self._applied = True

    def restore(self) -> None:
        """摘要：恢复被沙箱替换的运行时对象。"""
        global _ACTIVE_SANDBOX, _SANDBOX_ENABLED
        if not self._applied:
            return
        socket.socket = _ORIGINAL_SOCKET  # type: ignore[assignment]
        urllib.request.urlopen = _ORIGINAL_URLOPEN  # type: ignore[assignment]
        importlib.import_module = _ORIGINAL_IMPORT_MODULE  # type: ignore[assignment]
        builtins.__import__ = _ORIGINAL_IMPORT  # type: ignore[assignment]
        builtins.eval = _ORIGINAL_EVAL  # type: ignore[assignment]
        builtins.exec = _ORIGINAL_EXEC  # type: ignore[assignment]
        for module_name, module in self._saved_modules.items():
            if module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = module
        self._saved_modules.clear()
        _ACTIVE_SANDBOX = None
        _SANDBOX_ENABLED = False
        self._applied = False


class _GuardedSocket(_ORIGINAL_SOCKET):
    """摘要：仅允许本地地址 bind/connect 的 socket。"""

    def bind(self, address: Any) -> None:
        """摘要：阻断非本地地址监听。"""
        _ensure_local_address(address)
        return super().bind(address)

    def connect(self, address: Any) -> None:
        """摘要：阻断非本地地址连接。"""
        _ensure_local_address(address)
        return super().connect(address)

    def connect_ex(self, address: Any) -> int:
        """摘要：阻断非本地地址连接并返回原始 connect_ex 结果。"""
        _ensure_local_address(address)
        return super().connect_ex(address)


def _safe_eval(*_args, **_kwargs):
    module_name = str(sys._getframe(1).f_globals.get("__name__", ""))
    if module_name == "collections":
        return _ORIGINAL_EVAL(*_args, **_kwargs)
    raise SkillInvocationError("当前运行模式禁止使用 eval")


def _safe_exec(*args, **kwargs):
    module_name = str(sys._getframe(1).f_globals.get("__name__", ""))
    if module_name == "runpy" or module_name.startswith(("importlib", "_frozen_importlib")):
        return _ORIGINAL_EXEC(*args, **kwargs)
    raise SkillInvocationError("当前运行模式禁止使用 exec")


def _is_allowed_import(name: str) -> bool:
    """摘要：判断模块是否在 Skill 运行时导入白名单中。"""
    root_name = (name or "").split(".", 1)[0]
    return root_name in _ALLOWED_IMPORTS


def _is_blocked_import(name: str) -> bool:
    """摘要：判断模块是否属于明确禁用的网络客户端模块。"""
    root_name = (name or "").split(".", 1)[0]
    return root_name in _NETWORK_MODULES


def _safe_import_module(name: str, *args, **kwargs):
    if _is_blocked_import(name):
        raise SkillInvocationError(f"当前运行模式禁止动态导入模块: {name}")
    return _ORIGINAL_IMPORT_MODULE(name, *args, **kwargs)


def _safe_builtin_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
    if _is_blocked_import(name):
        raise SkillInvocationError(f"当前运行模式禁止导入模块: {name}")
    if _is_allowed_import(name) or name.startswith("_pytest"):
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    if getattr(sys, "frozen", False):
        if name in {"PyInstaller", "pkgutil", "importlib", "pkg_resources"}:
            return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
        if name.startswith("_frozen_importlib"):
            return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    if name in sys.builtin_module_names:
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)


def _safe_socket(*args, **kwargs):
    raise SkillInvocationError("当前运行模式禁止创建网络 socket")


def _safe_urlopen(*args, **kwargs):
    raise SkillInvocationError("当前运行模式禁止发起网络请求")


def _ensure_local_address(address: Any) -> None:
    host = _extract_host(address)
    if host is None or _is_local_host(host):
        return
    raise SkillInvocationError("Skill 未声明网络权限，禁止连接非本地地址")


def _extract_host(address: Any) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    if isinstance(address, str):
        return None
    return None


def _is_local_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized in {"", "localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


def enable_runtime_sandbox() -> None:
    """摘要：启用默认运行时沙箱，完全禁止 socket 创建。"""
    global _ACTIVE_SANDBOX
    if _SANDBOX_ENABLED:
        return
    sandbox = RuntimeSandbox()
    sandbox.apply()
    _ACTIVE_SANDBOX = sandbox


def disable_runtime_sandbox() -> None:
    """摘要：恢复运行时危险能力，便于测试与本地调试。"""
    if _ACTIVE_SANDBOX is None:
        return
    _ACTIVE_SANDBOX.restore()


@contextmanager
def runtime_sandbox(*, allow_local_socket: bool = False) -> Iterator[None]:
    """摘要：以上下文管理器形式临时启用运行时沙箱。"""
    sandbox = RuntimeSandbox(allow_local_socket=allow_local_socket)
    sandbox.apply()
    try:
        yield
    finally:
        sandbox.restore()
