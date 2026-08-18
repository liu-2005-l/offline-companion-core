"""性能回归基准测试。"""

from __future__ import annotations

import time

import pytest

from offline_companion.core.event_stream import EventStream, build_default_registry

BASELINES = {"event_append_100": 30.0}


@pytest.mark.benchmark
def test_event_append_100() -> None:
    """验证事件流批量 append 未出现明显回归。"""
    stream = EventStream("benchmark", build_default_registry())
    started = time.perf_counter()
    for index in range(100):
        stream.append("session/turn_start", {"index": index})
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < BASELINES["event_append_100"] * 3
