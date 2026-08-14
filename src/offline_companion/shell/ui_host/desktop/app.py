"""app：桌面主窗口、托盘与单实例（Sprint 6.8）。"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import time

from offline_companion import __version__
from offline_companion.shared.types import PrivacyMode
from offline_companion.shell.ui_host.bootstrap import (
    bootstrap_ui_session_or_exit,
    resolve_app_paths,
)
from offline_companion.shell.ui_host.desktop.crash_reporting import (
    check_previous_crash,
    mark_app_started,
    mark_app_stopped,
    setup_crash_handler,
)
from offline_companion.shell.ui_host.desktop.http_host import start_desktop_http
from offline_companion.shell.ui_host.desktop.instance_ipc import (
    remove_pid_file,
    should_handoff_to_running_instance,
    start_activation_listener,
    write_pid_file,
)
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.storage.settings_store import load_settings

_WINDOW_TITLE = "Offline Companion"
_TRAY_TITLE = "Offline Companion"
_ALLOWED_HOST = "127.0.0.1"
_DEFAULT_WINDOW_BOUNDS = {"width": 960, "height": 640}


class WindowAPI:
    """摘要：暴露给 pywebview 前端的窗口控制桥接对象。

    参数：
        window_holder: 延迟持有 pywebview Window 的字典，避免 create_window 前循环引用。
        close_callback: 关闭窗口时复用主进程的托盘/退出决策。
    """

    def __init__(self, window_holder: dict[str, object | None], close_callback) -> None:
        self._window_holder = window_holder
        self._close_callback = close_callback
        self._maximized = False

    def minimize(self) -> dict[str, bool]:
        """摘要：最小化当前桌面窗口。"""
        window = self._window()
        if window is not None:
            window.minimize()
        return {"ok": window is not None}

    def toggle_maximize(self) -> dict[str, bool]:
        """摘要：在最大化与还原之间切换窗口。"""
        window = self._window()
        if window is None:
            return {"ok": False, "maximized": self._maximized}
        if self._maximized:
            window.restore()
            self._maximized = False
        else:
            window.maximize()
            self._maximized = True
        return {"ok": True, "maximized": self._maximized}

    def close(self) -> dict[str, bool]:
        """摘要：请求关闭桌面窗口，按用户设置选择缩到托盘或退出。"""
        return self._close_callback()

    def set_bounds(self, x: int, y: int, width: int, height: int) -> dict[str, bool | int]:
        """摘要：移动并调整窗口大小，供自定义拖拽与缩放手柄调用。"""
        window = self._window()
        if window is None:
            return {"ok": False}
        safe_width = max(720, int(width))
        safe_height = max(480, int(height))
        window.move(int(x), int(y))
        window.resize(safe_width, safe_height)
        self._maximized = False
        return {"ok": True, "x": int(x), "y": int(y), "width": safe_width, "height": safe_height}

    def get_bounds(self) -> dict[str, bool | int]:
        """摘要：返回 pywebview 已知的窗口边界；缺失字段时返回默认安全值。"""
        window = self._window()
        if window is None:
            return {"ok": False, "x": 0, "y": 0, "width": 960, "height": 640, "maximized": self._maximized}
        return {
            "ok": True,
            "x": int(getattr(window, "x", 0) or 0),
            "y": int(getattr(window, "y", 0) or 0),
            "width": int(getattr(window, "width", 960) or 960),
            "height": int(getattr(window, "height", 640) or 640),
            "maximized": self._maximized,
        }

    def is_maximized(self) -> dict[str, bool]:
        """摘要：返回 bridge 维护的最大化状态。"""
        return {"ok": True, "maximized": self._maximized}

    def _window(self):
        return self._window_holder.get("window")


def _shutdown_runtime(bundle) -> None:
    """摘要：在强制结束桌面进程前显式释放后端与数据库资源。"""
    backend = getattr(bundle.orchestrator, "backend", None)
    stop = getattr(backend, "stop", None)
    if callable(stop):
        try:
            stop()
        except Exception as exc:
            print(f"警告：停止推理后端失败: {exc}", file=sys.stderr)
    close = getattr(bundle.conn, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:
            print(f"警告：关闭数据库连接失败: {exc}", file=sys.stderr)


def _require_desktop_deps() -> None:
    """摘要：确保桌面可选依赖已安装。"""
    try:
        import webview  # noqa: F401
    except ImportError as e:
        raise ImportError("桌面壳需要 pywebview：pip install -e '.[desktop]'") from e


def _initial_window_bounds(data_root) -> dict[str, int]:
    """摘要：读取并校验持久化窗口位置，缺失时返回默认尺寸。

    参数：
        data_root: 应用数据根目录。
    返回值：
        可传给 pywebview.create_window 的窗口边界参数。
    """
    raw = load_settings(data_root).get("window_bounds")
    if not isinstance(raw, dict):
        return dict(_DEFAULT_WINDOW_BOUNDS)
    width = max(720, int(raw.get("width") or _DEFAULT_WINDOW_BOUNDS["width"]))
    height = max(480, int(raw.get("height") or _DEFAULT_WINDOW_BOUNDS["height"]))
    bounds = {"width": width, "height": height}
    if raw.get("x") is not None:
        bounds["x"] = int(raw["x"])
    if raw.get("y") is not None:
        bounds["y"] = int(raw["y"])
    return bounds


def run_desktop(args: argparse.Namespace) -> int:
    """摘要：启动桌面壳（独立窗口 + 托盘驻留 + 单实例）。

    参数：
        args: CLI 命名空间（``persona``、``data_dir``、``memory`` 等）。

    返回值：
        进程退出码。
    """
    _require_desktop_deps()
    import webview

    paths = resolve_app_paths(getattr(args, "data_dir", None))
    force_new = bool(getattr(args, "force", False))
    if not force_new and should_handoff_to_running_instance(paths.root):
        print(
            "检测到已有桌面壳在运行，已尝试显示其窗口。\n"
            "若界面/代码未更新：托盘「退出」后仍可能有残留 python 进程；"
            "可用 desktop --force 强制启动新实例，或在任务管理器结束 python。",
            file=sys.stderr,
        )
        return 0

    previous_crash = check_previous_crash(paths.root)
    setup_crash_handler(paths.root)
    mark_app_started(paths.root)
    try:
        bundle = bootstrap_ui_session_or_exit(args, session_title="Desktop")
    except SystemExit:
        mark_app_stopped(paths.root)
        raise
    runtime = DesktopRuntime.from_bundle(bundle)
    runtime.pending_crash_log = str(previous_crash.path) if previous_crash is not None else None
    http = start_desktop_http(runtime)
    time.sleep(0.3)
    load_url = f"http://{_ALLOWED_HOST}:{http.port}/"

    write_pid_file(bundle.paths.root)

    window_holder: dict[str, webview.Window | None] = {"window": None}
    tray_icon = None
    tray_ready = False
    hide_to_tray_hint_shown = False
    is_quitting = False
    data_root = bundle.paths.root

    def show_main_window() -> None:
        win = window_holder["window"]
        if win is not None:
            win.show()

    start_activation_listener(show_main_window)

    def begin_quit() -> bool:
        """摘要：只执行一次退出清理；返回本次是否首次进入退出流程。"""
        nonlocal is_quitting
        if is_quitting:
            return False
        is_quitting = True
        remove_pid_file(data_root)
        _shutdown_runtime(bundle)
        mark_app_stopped(data_root)
        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception:
                pass
        return True

    def on_request_quit() -> None:
        """摘要：托盘退出须真正结束进程，避免残留占用 18766 与旧 UI。"""
        begin_quit()
        win = window_holder["window"]
        if win is None:
            os._exit(0)
            return

        def _destroy_window() -> None:
            try:
                win.destroy()
            except Exception:
                os._exit(0)

        # 不在 pystray/JS bridge 回调栈里同步 destroy，避免 WinForms closing 重入。
        threading.Timer(0.05, _destroy_window).start()

    def start_tray() -> bool:
        """摘要：启动系统托盘；失败时关窗将直接退出（避免无托盘却后台驻留）。"""
        nonlocal tray_icon, tray_ready
        try:
            import pystray
            from PIL import Image
        except ImportError as e:
            print(
                "警告：未安装 pystray/Pillow，托盘不可用；关闭窗口将直接退出应用。\n"
                f"  安装：pip install -e \".[desktop]\"  ({e})",
                file=sys.stderr,
            )
            return False

        # 暖色圆点图标，便于在托盘/隐藏图标区辨认
        image = Image.new("RGB", (64, 64), color=(255, 107, 157))

        def _show(_icon, _item) -> None:
            show_main_window()

        def _quit(_icon, _item) -> None:
            on_request_quit()

        def _about(_icon, _item) -> None:
            try:
                ctypes.windll.user32.MessageBoxW(
                    None,
                    "\n".join(
                        [
                            "Offline Companion",
                            f"版本：{__version__}",
                            f"模型：{runtime.model_label}",
                            "架构：PyInstaller + llama-server sidecar",
                            "许可证：BSD-2-Clause",
                            "仓库：offline-companion-core",
                        ]
                    ),
                    "关于 Offline Companion",
                    0x40,
                )
            except (AttributeError, OSError) as exc:
                print(f"无法显示关于窗口: {exc}", file=sys.stderr)

        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", _show, default=True),
            pystray.MenuItem("关于 Offline Companion", _about),
            pystray.MenuItem("退出", _quit),
        )
        tray_icon = pystray.Icon(_TRAY_TITLE, image, _WINDOW_TITLE, menu)
        tray_icon.run_detached()
        tray_ready = True
        print(
            "托盘已启用：点窗口 ✕ 将缩到后台。\n"
            "  图标可能在任务栏右侧「^」隐藏图标区；右键可「显示主窗口」或「退出」。",
            file=sys.stderr,
        )
        return True

    def should_close_to_tray() -> bool:
        """摘要：读取用户关闭行为设置，默认保持历史行为：缩到托盘。"""
        return bool(load_settings(data_root).get("close_to_tray", True))

    def request_window_close() -> dict[str, bool | str]:
        """摘要：按设置关闭窗口；托盘可用且允许时隐藏，否则退出进程。"""
        nonlocal hide_to_tray_hint_shown
        close_to_tray = should_close_to_tray()
        if not tray_ready or not close_to_tray:
            # 无托盘时禁止「假后台」：直接退出
            reason = "托盘不可用" if not tray_ready else "已关闭缩到托盘"
            print(f"{reason}，正在退出…", file=sys.stderr)
            begin_quit()
            win = window_holder["window"]
            if win is not None:
                def _destroy_window() -> None:
                    try:
                        win.destroy()
                    except Exception:
                        os._exit(0)

                threading.Timer(0.05, _destroy_window).start()
            return {"ok": True, "action": "quit"}

        win = window_holder["window"]
        if win is not None:
            win.hide()
        if tray_icon is not None and not hide_to_tray_hint_shown:
            hide_to_tray_hint_shown = True
            try:
                tray_icon.notify(
                    "Offline Companion 仍在后台运行",
                    "在任务栏托盘（或 ^ 隐藏区）右键可恢复或退出",
                )
            except Exception:
                pass
        return {"ok": True, "action": "tray"}

    def on_closing() -> bool:
        if is_quitting:
            return True
        close_to_tray = should_close_to_tray()
        if not tray_ready or not close_to_tray:
            reason = "托盘不可用" if not tray_ready else "已关闭缩到托盘"
            print(f"{reason}，正在退出…", file=sys.stderr)
            begin_quit()
            return True
        request_window_close()
        return False

    window_bounds = _initial_window_bounds(paths.root)
    window = webview.create_window(
        _WINDOW_TITLE,
        url=load_url,
        js_api=WindowAPI(window_holder, request_window_close),
        **window_bounds,
        min_size=(720, 480),
        frameless=True,
        easy_drag=False,
    )
    window_holder["window"] = window
    window.events.closing += on_closing

    start_tray()
    print(
        f"桌面壳已启动（Memory: {'on' if runtime.memory_on else 'off'}；"
        f"模型: {runtime.model_label}；托盘: "
        f"{'开' if tray_ready else '关'}）",
        file=sys.stderr,
    )
    try:
        webview.start(debug=False)
    finally:
        begin_quit()
    return 0


def add_desktop_arguments(parser: argparse.ArgumentParser) -> None:
    """摘要：向解析器注册桌面壳 CLI 参数。"""
    parser.add_argument(
        "--persona",
        type=str,
        default=None,
        help="persona YAML（默认 configs/personas/default.yaml）",
    )
    parser.add_argument("--session-id", type=str, default="desktop-default")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument(
        "--memory",
        type=int,
        default=None,
        help="1=on 0=off；省略则用人设 default",
    )
    parser.add_argument(
        "--privacy",
        type=str,
        default=PrivacyMode.LOCAL_ONLY.value,
        choices=[m.value for m in PrivacyMode],
    )
    parser.add_argument("--model", type=str, default=None, help="Path to .gguf（省略则 Echo）")
    parser.add_argument("--n-ctx", type=int, default=2048)
    parser.add_argument("--n-gpu-layers", type=int, default=0)
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略单实例检测，强制启动新进程（开发/Code 更新时用）",
    )


def register_desktop_subcommand(sub) -> argparse.ArgumentParser:
    """摘要：注册 ``desktop`` 子命令。"""
    desktop = sub.add_parser("desktop", help="启动桌面壳（pywebview；产品 UI）")
    add_desktop_arguments(desktop)
    return desktop


def main(argv: list[str] | None = None) -> int:
    """摘要：PyInstaller ``desktop`` 入口（``desktop.app:main``）。"""
    from offline_companion.shell.ui_host.cli import _default_persona_path
    from offline_companion.shell.ui_host.portable_runtime import bootstrap_if_frozen

    bootstrap_if_frozen()
    parser = argparse.ArgumentParser(prog="offline_companion-desktop")
    add_desktop_arguments(parser)
    ns = parser.parse_args(argv if argv is not None else None)
    if ns.persona is None:
        ns.persona = _default_persona_path()
    ns.memory = None if ns.memory is None else bool(ns.memory)
    return run_desktop(ns)


if __name__ == "__main__":
    raise SystemExit(main())
