"""app：桌面主窗口、托盘与单实例（Sprint 6.8）。"""

from __future__ import annotations

import argparse
import os
import sys
import time

from offline_companion.shell.ui_host.bootstrap import bootstrap_ui_session_or_exit, resolve_app_paths
from offline_companion.shell.ui_host.desktop.http_host import start_desktop_http
from offline_companion.shell.ui_host.desktop.instance_ipc import (
    remove_pid_file,
    should_handoff_to_running_instance,
    start_activation_listener,
    write_pid_file,
)
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shared.types import PrivacyMode

_WINDOW_TITLE = "Offline Companion"
_TRAY_TITLE = "Offline Companion"
_ALLOWED_HOST = "127.0.0.1"


def _require_desktop_deps() -> None:
    """摘要：确保桌面可选依赖已安装。"""
    try:
        import webview  # noqa: F401
    except ImportError as e:
        raise ImportError("桌面壳需要 pywebview：pip install -e '.[desktop]'") from e


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

    bundle = bootstrap_ui_session_or_exit(args, session_title="Desktop")
    runtime = DesktopRuntime.from_bundle(bundle)
    http = start_desktop_http(runtime)
    time.sleep(0.3)
    load_url = f"http://{_ALLOWED_HOST}:{http.port}/"

    write_pid_file(bundle.paths.root)

    window_holder: dict[str, webview.Window | None] = {"window": None}
    tray_icon = None
    tray_ready = False
    hide_to_tray_hint_shown = False
    data_root = bundle.paths.root

    def show_main_window() -> None:
        win = window_holder["window"]
        if win is not None:
            win.show()

    start_activation_listener(show_main_window)

    def on_request_quit() -> None:
        """摘要：托盘退出须真正结束进程，避免残留占用 18766 与旧 UI。"""
        remove_pid_file(data_root)
        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception:
                pass
        for win in list(webview.windows):
            try:
                win.destroy()
            except Exception:
                pass
        # pystray 回调不在 webview 主线程；destroy 可能无法让 start() 返回
        os._exit(0)

    def start_tray() -> bool:
        """摘要：启动系统托盘；失败时关窗将直接退出（避免无托盘却后台驻留）。"""
        nonlocal tray_icon, tray_ready
        try:
            from PIL import Image
            import pystray
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

        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", _show, default=True),
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

    def on_closing() -> bool:
        nonlocal hide_to_tray_hint_shown
        if not tray_ready:
            # 无托盘时禁止「假后台」：直接退出
            print("托盘不可用，正在退出…", file=sys.stderr)
            on_request_quit()
            return False

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
        return False

    window = webview.create_window(
        _WINDOW_TITLE,
        url=load_url,
        width=960,
        height=640,
        min_size=(720, 480),
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
    webview.start(debug=False)
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
