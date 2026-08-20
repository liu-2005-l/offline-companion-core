"""桌面崩溃日志与 sentinel 生命周期测试。"""

from __future__ import annotations

import sys
from pathlib import Path

from offline_companion.shell.ui_host.desktop.crash_reporting import (
    archive_crash_report,
    check_previous_crash,
    mark_app_started,
    mark_app_stopped,
    setup_crash_handler,
    write_crash_report,
)


def _write_test_crash(data_root: Path) -> Path:
    try:
        raise RuntimeError("模拟崩溃")
    except RuntimeError as exc:
        return write_crash_report(
            data_root,
            type(exc),
            exc,
            exc.__traceback__,
            source="test",
        )


def test_crash_log_written_with_traceback(tmp_path: Path) -> None:
    crash_path = _write_test_crash(tmp_path)

    content = crash_path.read_text(encoding="utf-8")
    assert crash_path.parent == tmp_path / "crashes"
    assert "RuntimeError: 模拟崩溃" in content
    assert "Traceback:" in content


def test_installed_main_hook_writes_local_report(tmp_path: Path, monkeypatch) -> None:
    forwarded: list[type[BaseException]] = []
    monkeypatch.setattr(sys, "excepthook", lambda exc_type, _value, _traceback: forwarded.append(exc_type))
    installation = setup_crash_handler(tmp_path)
    try:
        error = ValueError("hook failure")
        sys.excepthook(type(error), error, error.__traceback__)
    finally:
        installation.restore()

    reports = list((tmp_path / "crashes").glob("crash_*.log"))
    assert len(reports) == 1
    assert forwarded == [ValueError]


def test_detect_previous_crash_requires_running_sentinel(tmp_path: Path) -> None:
    assert check_previous_crash(tmp_path) is None
    mark_app_started(tmp_path)
    crash_path = _write_test_crash(tmp_path)

    pending = check_previous_crash(tmp_path)

    assert pending is not None
    assert pending.path == crash_path
    assert "模拟崩溃" in pending.content


def test_detect_previous_crash_uses_filesystem_timestamps(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("offline_companion.shell.ui_host.desktop.crash_reporting.time.time", lambda: 9e9)
    mark_app_started(tmp_path)
    crash_path = _write_test_crash(tmp_path)

    pending = check_previous_crash(tmp_path)

    assert pending is not None
    assert pending.path == crash_path


def test_normal_exit_clears_sentinel_and_prevents_report(tmp_path: Path) -> None:
    mark_app_started(tmp_path)
    _write_test_crash(tmp_path)
    mark_app_stopped(tmp_path)

    assert not (tmp_path / ".app_running").exists()
    assert check_previous_crash(tmp_path) is None


def test_archive_crash_report_moves_file(tmp_path: Path) -> None:
    crash_path = _write_test_crash(tmp_path)

    archived = archive_crash_report(tmp_path, crash_path, category="archived")

    assert not crash_path.exists()
    assert archived.parent == tmp_path / "crashes" / "archived"
    assert archived.is_file()
