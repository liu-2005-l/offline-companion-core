"""桌面窗口 JS bridge 测试。"""

from __future__ import annotations

from offline_companion.shell.ui_host.desktop import app as desktop_app
from offline_companion.shell.ui_host.desktop.app import (
    WindowAPI,
    _ensure_dpi_awareness,
    _initial_window_bounds,
    _monitor_work_area,
    _point_work_area,
    _windows_work_area,
)
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


class _FakeIntPtr:
    def __init__(self, value: int) -> None:
        self.value = value

    def ToInt64(self) -> int:
        return self.value


class _FakeDpiApi:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, ...]] = []

    def __call__(self, *args: int) -> int:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return 0


class _FakeMonitorUser32:
    def __init__(self) -> None:
        self.window_calls: list[tuple[int, int]] = []
        self.point_calls: list[tuple[int, int, int]] = []
        self.system_calls: list[int] = []
        self.set_window_calls: list[tuple[int, int, int, int, int, int]] = []
        self.window_monitor = 101
        self.point_monitor = 202
        self.window_rect = (-1700, 100, -740, 740)
        self.work_areas = {
            101: (-1920, 0, 0, 1040),
            202: (0, 0, 2560, 1528),
        }
        self.work_area_sequences: dict[int, list[tuple[int, int, int, int]]] = {}

    def MonitorFromWindow(self, hwnd, fallback: int) -> int:
        self.window_calls.append((hwnd.value, fallback))
        return self.window_monitor

    def MonitorFromPoint(self, point, fallback: int) -> int:
        self.point_calls.append((point.x, point.y, fallback))
        return self.point_monitor

    def GetMonitorInfoW(self, monitor: int, info_pointer) -> int:
        info = info_pointer._obj
        sequence = self.work_area_sequences.get(monitor)
        if sequence:
            left, top, right, bottom = sequence.pop(0)
        else:
            left, top, right, bottom = self.work_areas[monitor]
        info.rcWork.left, info.rcWork.top = left, top
        info.rcWork.right, info.rcWork.bottom = right, bottom
        return 1

    def GetWindowRect(self, _hwnd, rect_pointer) -> int:
        rect = rect_pointer._obj
        rect.left, rect.top, rect.right, rect.bottom = self.window_rect
        return 1

    def SetWindowPos(
        self,
        hwnd,
        _insert_after,
        x: int,
        y: int,
        width: int,
        height: int,
        flags: int,
    ) -> int:
        self.set_window_calls.append((hwnd.value, x, y, width, height, flags))
        self.window_rect = (x, y, x + width, y + height)
        return 1

    def SystemParametersInfoW(self, action: int, _param: int, rect_pointer, _flags: int) -> int:
        self.system_calls.append(action)
        rect = rect_pointer._obj
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1707, 1019
        return 1


def test_window_api_minimize_and_toggle_maximize(monkeypatch) -> None:
    window = _FakeWindow()
    api = WindowAPI({"window": window}, lambda: None)
    monkeypatch.setattr(desktop_app.os, "name", "posix")

    assert api.minimize() == {"ok": True}
    assert window.calls[-1] == ("minimize", ())

    assert api.toggle_maximize() == {"ok": True, "maximized": True}
    assert window.calls[-1] == ("maximize", ())
    assert api.is_maximized() == {"ok": True, "maximized": True}

    assert api.toggle_maximize() == {"ok": True, "maximized": False}
    assert window.calls[-1] == ("restore", ())
    assert api.is_maximized() == {"ok": True, "maximized": False}


def test_window_api_acquires_and_caches_64_bit_hwnd() -> None:
    window = _FakeWindow()
    window.native = type("FakeNative", (), {"Handle": _FakeIntPtr(5_000_000_000)})()
    api = WindowAPI({"window": window}, lambda: None)

    assert api._acquire_hwnd() is True
    assert api._hwnd == 5_000_000_000

    window.native.Handle = _FakeIntPtr(99)
    assert api._acquire_hwnd() is True
    assert api._hwnd == 5_000_000_000


def test_window_api_logs_hwnd_degrade_once_and_can_retry(caplog) -> None:
    window = _FakeWindow()
    api = WindowAPI({"window": window}, lambda: None)
    caplog.set_level("WARNING", logger=desktop_app.logger.name)

    assert api._acquire_hwnd() is False
    assert api._acquire_hwnd() is False
    assert [record.message for record in caplog.records] == [
        "native.Handle 不可用，窗口控制降级到 pywebview move/resize"
    ]

    window.native = type("FakeNative", (), {"Handle": _FakeIntPtr(1234)})()
    assert api._acquire_hwnd() is True
    assert api._hwnd == 1234


def test_ensure_dpi_awareness_prefers_per_monitor(monkeypatch) -> None:
    per_monitor = _FakeDpiApi()
    system = _FakeDpiApi()
    windll = type(
        "FakeWindll",
        (),
        {
            "shcore": type("FakeShcore", (), {"SetProcessDpiAwareness": per_monitor})(),
            "user32": type("FakeUser32", (), {"SetProcessDPIAware": system})(),
        },
    )()
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    _ensure_dpi_awareness()

    assert per_monitor.calls == [(2,)]
    assert system.calls == []


def test_ensure_dpi_awareness_falls_back_to_system(monkeypatch) -> None:
    per_monitor = _FakeDpiApi(OSError("shcore unavailable"))
    system = _FakeDpiApi()
    windll = type(
        "FakeWindll",
        (),
        {
            "shcore": type("FakeShcore", (), {"SetProcessDpiAwareness": per_monitor})(),
            "user32": type("FakeUser32", (), {"SetProcessDPIAware": system})(),
        },
    )()
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    _ensure_dpi_awareness()

    assert per_monitor.calls == [(2,)]
    assert system.calls == [()]


def test_monitor_work_area_uses_window_monitor(monkeypatch) -> None:
    user32 = _FakeMonitorUser32()
    windll = type("FakeWindll", (), {"user32": user32})()
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    assert _monitor_work_area(88) == (-1920, 0, 0, 1040)
    assert user32.window_calls == [(88, 2)]


def test_point_work_area_uses_nearest_monitor(monkeypatch) -> None:
    user32 = _FakeMonitorUser32()
    windll = type("FakeWindll", (), {"user32": user32})()
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    assert _point_work_area(2000, 800) == (0, 0, 2560, 1528)
    assert user32.point_calls == [(2000, 800, 2)]


def test_windows_work_area_remains_primary_monitor_fallback(monkeypatch) -> None:
    user32 = _FakeMonitorUser32()
    windll = type("FakeWindll", (), {"user32": user32})()
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    assert _windows_work_area() == (0, 0, 1707, 1019)
    assert user32.system_calls == [0x0030]


def test_window_api_set_bounds_clamps_minimum_size(monkeypatch) -> None:
    window = _FakeWindow()
    api = WindowAPI({"window": window}, lambda: None)
    monkeypatch.setattr(desktop_app.os, "name", "posix")

    assert api.toggle_maximize() == {"ok": True, "maximized": True}
    result = api.set_bounds(1, 2, 100, 200)

    assert result == {"ok": True, "x": 1, "y": 2, "width": 720, "height": 480}
    assert window.calls[-2:] == [("move", (1, 2)), ("resize", (720, 480))]
    assert api.get_bounds()["width"] == 720
    assert api.is_maximized() == {"ok": True, "maximized": False}


def test_window_api_uses_physical_work_area_and_restores_exact_rect(monkeypatch) -> None:
    user32 = _FakeMonitorUser32()
    user32.point_monitor = 101
    windll = type("FakeWindll", (), {"user32": user32})()
    window = _FakeWindow()
    window.native = type("FakeNative", (), {"Handle": _FakeIntPtr(88)})()
    api = WindowAPI({"window": window}, lambda: None)
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    assert api.toggle_maximize() == {"ok": True, "maximized": True}
    assert user32.set_window_calls[-1] == (88, -1920, 0, 1920, 1040, 0x0014)

    assert api.toggle_maximize() == {"ok": True, "maximized": False}
    assert user32.set_window_calls[-1] == (88, -1700, 100, 960, 640, 0x0014)


def test_window_api_rechecks_work_area_once_after_maximize(monkeypatch) -> None:
    user32 = _FakeMonitorUser32()
    user32.window_monitor = 202
    user32.work_area_sequences[202] = [
        (0, 0, 2560, 1528),
        (0, 0, 1920, 1040),
    ]
    windll = type("FakeWindll", (), {"user32": user32})()
    window = _FakeWindow()
    window.native = type("FakeNative", (), {"Handle": _FakeIntPtr(88)})()
    api = WindowAPI({"window": window}, lambda: None)
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    assert api.toggle_maximize() == {"ok": True, "maximized": True}
    assert user32.set_window_calls[-2:] == [
        (88, 0, 0, 2560, 1528, 0x0014),
        (88, 0, 0, 1920, 1040, 0x0014),
    ]


def test_window_api_restore_clamps_size_before_position(monkeypatch) -> None:
    user32 = _FakeMonitorUser32()
    user32.work_areas[202] = (0, 0, 1280, 720)
    windll = type("FakeWindll", (), {"user32": user32})()
    window = _FakeWindow()
    window.native = type("FakeNative", (), {"Handle": _FakeIntPtr(88)})()
    api = WindowAPI({"window": window}, lambda: None)
    api._maximized = True
    api._hwnd = 88
    api._saved_rect = (-1800, 100, 2500, 1300)
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    result = api.toggle_maximize()

    assert result == {"ok": True, "maximized": False}
    assert user32.set_window_calls[-1] == (88, 0, 0, 1280, 720, 0x0014)


def test_window_api_restore_without_saved_rect_uses_centered_work_area(monkeypatch) -> None:
    user32 = _FakeMonitorUser32()
    user32.window_monitor = 202
    windll = type("FakeWindll", (), {"user32": user32})()
    window = _FakeWindow()
    api = WindowAPI({"window": window}, lambda: None)
    api._maximized = True
    api._hwnd = 88
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    result = api.toggle_maximize()

    assert result == {"ok": True, "maximized": False}
    assert user32.set_window_calls[-1] == (88, 256, 153, 2048, 1222, 0x0014)


def test_window_api_degrades_to_pywebview_when_hwnd_is_unavailable(monkeypatch) -> None:
    user32 = _FakeMonitorUser32()
    windll = type("FakeWindll", (), {"user32": user32})()
    window = _FakeWindow()
    api = WindowAPI({"window": window}, lambda: None)
    monkeypatch.setattr(desktop_app.os, "name", "nt")
    monkeypatch.setattr(desktop_app.ctypes, "windll", windll, raising=False)

    assert api.toggle_maximize() == {"ok": True, "maximized": True}
    assert window.calls[-2:] == [("move", (0, 0)), ("resize", (1707, 1019))]

    assert api.toggle_maximize() == {"ok": True, "maximized": False}
    assert window.calls[-2:] == [("move", (10, 20)), ("resize", (960, 640))]


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
