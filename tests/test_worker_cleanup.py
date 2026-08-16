"""后台 worker 有界清理测试。"""

import asyncio

from offline_companion.core.lifecycle import cleanup_worker


def test_cleanup_worker_requests_stop_and_logs_timeout(caplog) -> None:
    calls: list[object] = []

    def stop() -> None:
        calls.append("stop")

    def join(timeout: float) -> None:
        calls.append(timeout)
        raise TimeoutError

    asyncio.run(cleanup_worker(stop, join, grace_timeout=0.25))

    assert calls == ["stop", 0.25]
    assert "Worker did not stop" in caplog.text
