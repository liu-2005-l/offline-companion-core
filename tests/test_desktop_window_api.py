"""桌面窗口 JS bridge 测试。"""

from __future__ import annotations

from offline_companion.shell.ui_host.desktop.app import WindowAPI, _initial_window_bounds
from offline_companion.storage.settings_store import update_settings


class _FakeWindow:
    def __init__(self) -> None:
        self.x = 10
        self.y = 20
        self.width = 960
        self.height = 640
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def minimize(self) -> None:
        self.calls.append(("minimize", ()))

    def maximize(self) -> None:
        self.calls.append(("maximize", ()))

    def restore(self) -> None:
        self.calls.append(("restore", ()))

    def move(self, x: int, y: int) -> None:
        self.x = x
        self.y = y
        self.calls.append(("move", (x, y)))

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.calls.append(("resize", (width, height)))


def test_window_api_minimize_and_toggle_maximize() -> None:
    window = _FakeWindow()
    api = WindowAPI({"window": window}, lambda: None)

    assert api.minimize() == {"ok": True}
    assert window.calls[-1] == ("minimize", ())

    assert api.toggle_maximize() == {"ok": True, "maximized": True}
    assert window.calls[-1] == ("maximize", ())
    assert api.is_maximized() == {"ok": True, "maximized": True}

    assert api.toggle_maximize() == {"ok": True, "maximized": False}
    assert window.calls[-1] == ("restore", ())
    assert api.is_maximized() == {"ok": True, "maximized": False}


def test_window_api_set_bounds_clamps_minimum_size() -> None:
    window = _FakeWindow()
    api = WindowAPI({"window": window}, lambda: None)

    assert api.toggle_maximize() == {"ok": True, "maximized": True}
    result = api.set_bounds(1, 2, 100, 200)

    assert result == {"ok": True, "x": 1, "y": 2, "width": 720, "height": 480}
    assert window.calls[-2:] == [("move", (1, 2)), ("resize", (720, 480))]
    assert api.get_bounds()["width"] == 720
    assert api.is_maximized() == {"ok": True, "maximized": False}


def test_window_api_close_uses_quit_callback() -> None:
    called: list[bool] = []
    api = WindowAPI({"window": _FakeWindow()}, lambda: called.append(True) or {"ok": True, "action": "quit"})

    assert api.close() == {"ok": True, "action": "quit"}
    assert called == [True]


def test_initial_window_bounds_reads_settings(tmp_path) -> None:
    update_settings(tmp_path, {"window_bounds": {"x": 11, "y": 22, "width": 100, "height": 200}})

    assert _initial_window_bounds(tmp_path) == {"width": 720, "height": 480, "x": 11, "y": 22}


def test_initial_window_bounds_defaults_without_settings(tmp_path) -> None:
    assert _initial_window_bounds(tmp_path) == {"width": 960, "height": 640}
