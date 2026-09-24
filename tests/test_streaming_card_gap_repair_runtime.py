"""摘要：在真实 JS 运行时验证 card gap repair 去重。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_streaming_card_gap_repair_replays_each_sequence_once() -> None:
    """摘要：补拉不得把已处理 card_delta 再次拼入 buffer。"""
    node = shutil.which("node")
    if node is None:
        pytest.fail("B3 合并门槛要求可用的 Node.js 运行时")

    completed = subprocess.run(
        [node, str(Path("tests/js/run_streaming_card_gap_repair.js"))],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"seen": [11, 12], "complete": True}
