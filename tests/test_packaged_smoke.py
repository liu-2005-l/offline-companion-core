"""便携包冒烟输出校验（无需构建 dist）。"""

from __future__ import annotations

from offline_companion.shell.ui_host.packaged_smoke_lib import validate_smoke_stdout


def test_validate_smoke_stdout_ok() -> None:
    sample = """
Session: webui-default
Privacy: local_only | Memory: on
(saved memory: 便携冒烟偏好 )
You> Bot> [no-model] 你好
"""
    assert validate_smoke_stdout(sample) == []


def test_validate_smoke_stdout_missing_bot() -> None:
    errs = validate_smoke_stdout("Session: x\nMemory: on\n")
    assert any("Bot>" in e for e in errs)
