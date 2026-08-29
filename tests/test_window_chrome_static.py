"""摘要：桌面窗口前端控制注册边界的静态回归测试。"""

from pathlib import Path

STATIC_DIR = (
    Path(__file__).resolve().parents[1]
    / "src/offline_companion/shell/ui_host/desktop/static"
)
ROOT_DIR = Path(__file__).resolve().parents[1]


def test_desktop_shell_uses_only_formal_window_chrome_handlers() -> None:
    prototype = (STATIC_DIR / "shell.js").read_text(encoding="utf-8")
    adapter = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")

    assert "window.__shellApiActive = true;" in adapter
    assert "function registerWindowChrome()" in adapter
    assert "registerWindowChrome();" in adapter
    assert "window.addEventListener('load'" in prototype
    assert "if (window.__shellApiActive) return;" in prototype
    assert "document.addEventListener('DOMContentLoaded', initResizeHandles);" not in prototype


def test_prototype_window_minimum_matches_native_window_minimum() -> None:
    prototype = (STATIC_DIR / "shell.js").read_text(encoding="utf-8")

    assert "var MIN_W = 720, MIN_H = 480;" in prototype


def test_resize_handles_use_pointer_capture_and_inward_hit_areas() -> None:
    adapter = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")
    stylesheet = (STATIC_DIR / "shell.css").read_text(encoding="utf-8")

    assert "addEventListener('pointerdown', beginWindowResize" in adapter
    assert "handle.setPointerCapture(event.pointerId)" in adapter
    assert "document.addEventListener('pointermove', moveWindowResize" in adapter
    assert "handle.releasePointerCapture" in adapter
    assert "api.begin_resize" not in adapter
    assert ".resize-n { top: 0;" in stylesheet
    assert ".resize-e { right: 0;" in stylesheet
    assert ".resize-se { bottom: 0; right: 0; width: 16px;" in stylesheet
    assert "top: -3px" not in stylesheet


def test_adaptive_layout_uses_single_javascript_breakpoint_source() -> None:
    adapter = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")
    stylesheet = (STATIC_DIR / "shell.css").read_text(encoding="utf-8")
    markup = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "function resolveLayout(width, height)" in adapter
    assert "width < 900 || height < 600" in adapter
    assert "width >= 1600 && height >= 900" in adapter
    assert "window.addEventListener('resize', applyAdaptiveLayout);" in adapter
    assert "requestAnimationFrame" in adapter
    assert "html[data-layout='compact']" in stylesheet
    assert "html[data-layout='wide']" in stylesheet
    assert "calc(100dvw - 32px)" in stylesheet
    assert "calc(100dvh - 32px)" in stylesheet
    assert 'data-layout="standard"' in markup
    assert "html[data-layout='compact'] .onboarding-overlay { padding: 16px; }" in stylesheet


def test_memory_default_range_tracks_local_today_and_previous_year() -> None:
    prototype = (STATIC_DIR / "shell.js").read_text(encoding="utf-8")

    assert "function defaultMemoryDateRange(referenceDate)" in prototype
    assert "referenceDate.getFullYear() - 1" in prototype
    assert "formatLocalDate(referenceDate)" in prototype
    assert "window.addEventListener('focus', refreshDefaultMemoryDateRange);" in prototype
    assert "function fmt(d) { return d.toISOString().slice(0, 10); }" not in prototype


def test_window_adaptive_design_fact_source_is_in_repo() -> None:
    design = (ROOT_DIR / "docs/window-adaptive-layout-design.md").read_text(encoding="utf-8")
    checklist = (ROOT_DIR / "docs/v1-7-0-release-checklist.md").read_text(encoding="utf-8")

    assert "窗口自适应布局设计 v3" in design
    assert "SetProcessDpiAwareness(2)" in design
    assert "MonitorFromWindow" in design
    assert "SetWindowPos(88,-1920,0,1920,1040,0x0014)" in design
    assert "G7 | 窗口布局验收行" in checklist


def test_desktop_window_native_entry_order_is_locked() -> None:
    source = (
        ROOT_DIR / "src/offline_companion/shell/ui_host/desktop/app.py"
    ).read_text(encoding="utf-8")

    assert source.index("    _ensure_dpi_awareness()\n    _require_desktop_deps()") < source.index("webview.create_window(")
    assert source.index("webview.create_window(") < source.index("webview.start(debug=False)")
    assert "frameless=True" in source
    assert "easy_drag=False" in source
    assert "min_size=(720, 480)" in source
