"""摘要：在真实 JS 运行时验证 B3 卡片生命周期。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_streaming_card_state_machine_runs_in_javascript() -> None:
    """摘要：三态、零 delta、retry 与断连必须通过 JS 运行态。"""
    node = shutil.which("node")
    if node is None:
        pytest.fail("B3 合并门槛要求可用的 Node.js 运行时")

    completed = subprocess.run(
        [node, str(Path("tests/js/run_streaming_card_b3_state.js"))],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"scenarios": 8}
