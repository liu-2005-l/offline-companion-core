"""instance_ipc：单实例激活（127.0.0.1 本地套接字；仅桌面壳进程内使用）。"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path

_ACTIVATE_HOST = "127.0.0.1"
_ACTIVATE_PORT = 18766
_SHOW_TOKEN = b"SHOW"
_PID_FILE = ".desktop_instance.pid"


def _pid_path(data_root: Path) -> Path:
    return data_root / _PID_FILE


def _pid_alive(pid: int) -> bool:
    """摘要：检测 PID 是否仍存在（Windows / POSIX）。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def clear_stale_pid_file(data_root: Path) -> None:
    """摘要：若 PID 文件指向已退出进程，则删除（托盘退出不完整时的恢复）。"""
    path = _pid_path(data_root)
    if not path.is_file():
        return
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return
    if not _pid_alive(pid):
        path.unlink(missing_ok=True)


def write_pid_file(data_root: Path) -> None:
    """摘要：登记当前进程 PID。"""
    path = _pid_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid_file(data_root: Path) -> None:
    """摘要：退出时移除 PID 登记。"""
    _pid_path(data_root).unlink(missing_ok=True)


def try_notify_running_instance() -> bool:
    """摘要：若已有实例在监听，发送 SHOW 并返回 True。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.5)
        sock.connect((_ACTIVATE_HOST, _ACTIVATE_PORT))
        sock.sendall(_SHOW_TOKEN)
        return True
    except OSError:
        return False
    finally:
        sock.close()


def should_handoff_to_running_instance(data_root: Path) -> bool:
    """摘要：是否应将本次启动交给已在运行的实例。

    先清理过期 PID 文件，再探测激活端口。
    """
    clear_stale_pid_file(data_root)
    if not try_notify_running_instance():
        return False
    # 端口有响应：再核对 PID（若登记了且仍存活才 handoff）
    path = _pid_path(data_root)
    if not path.is_file():
        return True
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return True
    return _pid_alive(pid)


def start_activation_listener(on_show: Callable[[], None]) -> socket.socket:
    """摘要：启动后台线程监听第二实例的激活请求。

    参数：
        on_show: 收到 SHOW 时回调（应在 UI 线程显示主窗口）。

    返回值：
        绑定的监听套接字（进程退出时随进程释放）。
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((_ACTIVATE_HOST, _ACTIVATE_PORT))
    server.listen(5)

    def _serve() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                break
            try:
                data = conn.recv(16)
                if data == _SHOW_TOKEN:
                    on_show()
            finally:
                conn.close()

    threading.Thread(target=_serve, daemon=True, name="desktop-activate").start()
    return server
