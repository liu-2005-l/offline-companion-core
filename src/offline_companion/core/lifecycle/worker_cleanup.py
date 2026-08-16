"""后台 worker 的有界协作式清理。"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


async def cleanup_worker(
    stop_fn: Callable[[], None],
    join_fn: Callable[[float], None],
    grace_timeout: float = 10.0,
) -> None:
    """摘要：请求 worker 停止并在限定时间内等待。

    参数：
        stop_fn: 协作式取消函数。
        join_fn: 接收超时秒数的等待函数。
        grace_timeout: 最大等待时间。
    """
    stop_fn()
    try:
        join_fn(max(0.0, float(grace_timeout)))
    except TimeoutError:
        logger.warning("Worker did not stop within %.1fs", grace_timeout)
