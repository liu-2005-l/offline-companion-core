"""桌面壳单实例 PID 文件与过期清理。"""

from __future__ import annotations

import os
from unittest.mock import patch

from offline_companion.shell.ui_host.desktop.instance_ipc import (
    clear_stale_pid_file,
    should_handoff_to_running_instance,
    write_pid_file,
)


def test_clear_stale_pid_file_removes_dead_pid(tmp_path) -> None:
    path = tmp_path / ".desktop_instance.pid"
    path.write_text("99999999", encoding="utf-8")
    clear_stale_pid_file(tmp_path)
    assert not path.is_file()


def test_write_pid_file_roundtrip(tmp_path) -> None:
    write_pid_file(tmp_path)
    pid = int((tmp_path / ".desktop_instance.pid").read_text(encoding="utf-8"))
    assert pid == os.getpid()


def test_should_not_handoff_when_port_closed(tmp_path) -> None:
    clear_stale_pid_file(tmp_path)
    with patch(
        "offline_companion.shell.ui_host.desktop.instance_ipc.try_notify_running_instance",
        return_value=False,
    ):
        assert should_handoff_to_running_instance(tmp_path) is False
