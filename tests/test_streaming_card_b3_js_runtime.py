"""摘要：在真实 JS 运行时中执行 B1/B3 共享 golden。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_streaming_card_js_runtime_matches_shared_golden() -> None:
    """摘要：JS 运行态必须逐字段通过全部共享 golden 节点。"""
    node = shutil.which("node")
    if node is None:
        pytest.fail("B3 合并门槛要求可用的 Node.js 运行时")
    runner = Path("tests/js/run_streaming_card_b1_golden.js")

    completed = subprocess.run(
        [node, str(runner)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"checked": 39}
