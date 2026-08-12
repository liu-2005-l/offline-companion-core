"""idle_detector：桌面 UI 层空闲检测器。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class IdleDetector:
    """摘要：基于最后输入时间检测用户空闲并触发回调。"""

    def __init__(
        self,
        *,
        threshold_seconds: float = 300.0,
        check_interval_seconds: float = 30.0,
        on_idle: Callable[[], None] | None = None,
        on_user_input: Callable[[], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """摘要：初始化空闲检测器。

        参数:
            threshold_seconds: 判定空闲所需的无输入秒数。
            check_interval_seconds: 后台线程检查间隔。
            on_idle: 空闲触发回调。
            on_user_input: 用户输入回调，用于协作式中断后台 IdleThink。
            clock: 可注入时钟，便于确定性测试。
        """
        if threshold_seconds <= 0:
            raise ValueError("threshold_seconds must be positive")
        if check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be positive")
        self._threshold_seconds = float(threshold_seconds)
        self._check_interval_seconds = float(check_interval_seconds)
        self._on_idle = on_idle
        self._on_user_input = on_user_input
        self._clock = clock or time.time
        self._last_input_at = self._clock()
        self._last_idle_at: float | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    @property
    def last_input_at(self) -> float:
        """摘要：返回最近一次输入时间戳。"""
        with self._lock:
            return self._last_input_at

    @property
    def last_idle_at(self) -> float | None:
        """摘要：返回最近一次空闲触发时间戳。"""
        with self._lock:
            return self._last_idle_at

    @property
    def running(self) -> bool:
        """摘要：返回后台检测线程是否处于运行状态。"""
        with self._lock:
            return self._running

    @property
    def threshold_seconds(self) -> float:
        """摘要：返回当前空闲阈值秒数。"""
        with self._lock:
            return self._threshold_seconds

    def set_threshold(self, threshold_seconds: float) -> None:
        """摘要：更新空闲阈值秒数。"""
        if threshold_seconds <= 0:
            raise ValueError("threshold_seconds must be positive")
        with self._lock:
            self._threshold_seconds = float(threshold_seconds)

    def touch(self) -> None:
        """摘要：用户产生输入活动时刷新空闲计时器。"""
        with self._lock:
            self._last_input_at = self._clock()
        if self._on_user_input is not None:
            try:
                self._on_user_input()
            except Exception:
                logger.exception("Idle user input callback failed")

    def start(self) -> None:
        """摘要：启动后台检测线程；重复调用不会重复启动。"""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="idle-detector")
        self._thread.start()
        logger.info(
            "IdleDetector started: threshold=%.1fs, check_interval=%.1fs",
            self._threshold_seconds,
            self._check_interval_seconds,
        )

    def stop(self) -> None:
        """摘要：停止后台检测线程。"""
        with self._lock:
            self._running = False
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def check_once(self, now: float | None = None) -> bool:
        """摘要：执行一次空闲检查，返回本次是否触发。

        参数:
            now: 可选当前时间戳；测试中用于避免真实等待。

        返回值:
            达到阈值并触发回调时返回 ``True``，否则返回 ``False``。
        """
        timestamp = self._clock() if now is None else float(now)
        with self._lock:
            elapsed = timestamp - self._last_input_at
            if elapsed < self._threshold_seconds:
                return False
            self._last_input_at = timestamp
            self._last_idle_at = timestamp
        logger.info("Idle detected after %.0fs, triggering", elapsed)
        if self._on_idle is not None:
            try:
                self._on_idle()
            except Exception:
                logger.exception("Idle callback failed")
        return True

    def _run(self) -> None:
        """摘要：后台线程循环；仅负责周期性调用单次检查。"""
        while True:
            with self._lock:
                if not self._running:
                    return
            if self._stop_event.wait(self._check_interval_seconds):
                return
            self.check_once()
