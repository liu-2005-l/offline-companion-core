"""桌面隐私模式 socket 热切守卫。"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

from offline_companion.shared.errors import OutboundDenied

_ORIGINAL_SOCKET = socket.socket
_GUARD_ENABLED = False


def is_socket_guard_enabled() -> bool:
    """摘要：返回桌面进程的非本地 socket 拦截是否已启用。"""
    return _GUARD_ENABLED


def enable_privacy_socket_guard() -> None:
    """摘要：启用桌面进程非本地 socket 拦截。

    说明：该守卫只阻止新建 socket 的非本地连接；已建立连接不会被主动中断。
    """
    global _GUARD_ENABLED
    if _GUARD_ENABLED:
        return
    socket.socket = _GuardedSocket  # type: ignore[assignment]
    _GUARD_ENABLED = True


def disable_privacy_socket_guard() -> None:
    """摘要：恢复桌面进程默认 socket 行为。"""
    global _GUARD_ENABLED
    if not _GUARD_ENABLED:
        return
    socket.socket = _ORIGINAL_SOCKET  # type: ignore[assignment]
    _GUARD_ENABLED = False


def apply_privacy_socket_guard(local_only: bool) -> bool:
    """摘要：按隐私模式启用或关闭 socket 守卫。

    参数：
        local_only: 为 True 时启用非本地连接拦截，否则关闭拦截。

    返回值：
        当前守卫是否处于启用状态。
    """
    if local_only:
        enable_privacy_socket_guard()
    else:
        disable_privacy_socket_guard()
    return is_socket_guard_enabled()


class _GuardedSocket(_ORIGINAL_SOCKET):
    """摘要：仅允许本机地址连接的 socket 子类。"""

    def connect(self, address: Any) -> None:
        _ensure_local_address(address)
        return super().connect(address)

    def connect_ex(self, address: Any) -> int:
        _ensure_local_address(address)
        return super().connect_ex(address)


def _ensure_local_address(address: Any) -> None:
    """摘要：阻止非本地地址连接。

    参数：
        address: socket.connect/connect_ex 接收的地址参数。

    Raises:
        OutboundDenied: 当目标不是本机地址时抛出。
    """
    host = _extract_host(address)
    if host is None or _is_local_host(host):
        return
    raise OutboundDenied("privacy_mode=local_only 禁止创建非本地 socket 连接")


def _extract_host(address: Any) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    if isinstance(address, str):
        return None
    return None


def _is_local_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return ip.is_loopback
