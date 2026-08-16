"""插件资源作用域。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from .types import Cleanup

logger = logging.getLogger(__name__)


class EffectScope:
    """摘要：以 LIFO 顺序托管插件资源并支持半初始化回滚。"""

    def __init__(self, name: str = "<anonymous>") -> None:
        self._name = name
        self._disposers: list[Cleanup] = []
        self._disposed = False
        self._dispose_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """返回作用域名称。"""
        return self._name

    @property
    def is_disposed(self) -> bool:
        """返回作用域是否已释放。"""
        return self._disposed

    def add(self, setup: Callable[[], Cleanup | None]) -> None:
        """摘要：立即执行 setup 并收集其返回的清理函数。

        参数：
            setup: 创建资源并返回 disposer 的函数。
        Raises:
            RuntimeError: 作用域已释放。
            Exception: setup 异常，已注册资源会先回滚。
        """
        self._ensure_open()
        try:
            disposer = setup()
            if disposer is not None:
                self._disposers.append(disposer)
        except Exception:
            logger.exception("Effect setup failed in %s, rolling back", self._name)
            self._rollback_sync()
            raise

    def add_disposer(self, disposer: Cleanup) -> None:
        """摘要：直接注册一个清理函数。"""
        self._ensure_open()
        self._disposers.append(disposer)

    async def dispose(self) -> None:
        """摘要：幂等地逆序执行所有 disposer，单个失败不阻断后续清理。"""
        if self._disposed:
            return
        async with self._dispose_lock:
            if self._disposed:
                return
            self._disposed = True
            while self._disposers:
                disposer = self._disposers.pop()
                try:
                    result = disposer()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logger.exception("Disposer failed in %s, continuing", self._name)

    def _ensure_open(self) -> None:
        if self._disposed:
            raise RuntimeError(f"EffectScope {self._name} already disposed")

    def _rollback_sync(self) -> None:
        while self._disposers:
            disposer = self._disposers.pop()
            try:
                result = disposer()
                if inspect.isawaitable(result):
                    self._schedule_awaitable(result)
            except Exception:
                logger.exception("Rollback disposer failed in %s", self._name)

    @staticmethod
    def _schedule_awaitable(awaitable: Any) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(awaitable)
        else:
            asyncio.create_task(awaitable)
