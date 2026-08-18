"""可插拔的运行时健康检查聚合器。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class HealthStatus(StrEnum):
    """摘要：单个组件或整体运行状态。"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HealthCheckResult:
    """摘要：一个组件的健康检查结果。"""

    component: str
    status: HealthStatus
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """摘要：转换为 JSON 可序列化的结果。"""
        return asdict(self) | {"status": self.status.value}


HealthCheck = Callable[[], HealthCheckResult]


class HealthChecker:
    """摘要：运行、缓存并聚合组件健康检查。"""

    def __init__(self, *, cache_seconds: float = 30.0) -> None:
        self._checks: dict[str, HealthCheck] = {}
        self._cache_seconds = max(0.0, cache_seconds)
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0

    def register(self, name: str, check: HealthCheck) -> Callable[[], None]:
        """摘要：注册检查并返回幂等释放器。"""
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("health check name 不能为空")
        if normalized in self._checks:
            raise ValueError(f"health check 已注册: {normalized}")
        self._checks[normalized] = check
        self._cached = None
        released = False

        def dispose() -> None:
            nonlocal released
            if released:
                return
            released = True
            self._checks.pop(normalized, None)
            self._cached = None

        return dispose

    def run_all(self, *, force: bool = False) -> dict[str, Any]:
        """摘要：运行全部检查并返回 overall/components 聚合结果。"""
        now = time.monotonic()
        if not force and self._cached is not None and now - self._cached_at < self._cache_seconds:
            return self._cached
        components: dict[str, HealthCheckResult] = {}
        for name, check in tuple(self._checks.items()):
            try:
                result = check()
                if result.component != name:
                    result = HealthCheckResult(name, result.status, result.detail, result.metrics)
            except Exception as exc:  # noqa: BLE001 - 单项检查必须隔离异常
                result = HealthCheckResult(name, HealthStatus.UNHEALTHY, f"检查失败: {exc}")
            components[name] = result
        statuses = [result.status for result in components.values()]
        overall = HealthStatus.HEALTHY
        if HealthStatus.UNHEALTHY in statuses:
            overall = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            overall = HealthStatus.DEGRADED
        elif not statuses:
            overall = HealthStatus.UNKNOWN
        result = {
            "overall": overall.value,
            "components": {name: item.as_dict() for name, item in components.items()},
            "checked_at": time.time(),
        }
        self._cached = result
        self._cached_at = now
        return result

    def component(self, name: str, *, force: bool = False) -> dict[str, Any] | None:
        """摘要：返回单组件检查结果，不存在时返回 ``None``。"""
        return self.run_all(force=force)["components"].get(name)
