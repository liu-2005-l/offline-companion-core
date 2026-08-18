"""健康检查聚合器与桌面诊断 API 测试。"""

from __future__ import annotations

from offline_companion.core.diagnostics import HealthChecker, HealthCheckResult, HealthStatus


def test_health_checker_aggregates_healthy_components() -> None:
    checker = HealthChecker()
    checker.register("one", lambda: HealthCheckResult("one", HealthStatus.HEALTHY, "ok"))
    checker.register("two", lambda: HealthCheckResult("two", HealthStatus.HEALTHY, "ok"))
    result = checker.run_all()
    assert result["overall"] == "healthy"
    assert set(result["components"]) == {"one", "two"}


def test_health_checker_uses_worst_status() -> None:
    checker = HealthChecker()
    checker.register("degraded", lambda: HealthCheckResult("degraded", HealthStatus.DEGRADED))
    checker.register("unhealthy", lambda: HealthCheckResult("unhealthy", HealthStatus.UNHEALTHY))
    assert checker.run_all()["overall"] == "unhealthy"


def test_health_checker_contains_check_failure() -> None:
    checker = HealthChecker()

    def fail() -> HealthCheckResult:
        raise RuntimeError("broken")

    checker.register("broken", fail)
    result = checker.run_all()
    assert result["overall"] == "unhealthy"
    assert result["components"]["broken"]["status"] == "unhealthy"


def test_health_checker_caches_until_forced() -> None:
    calls = 0
    checker = HealthChecker(cache_seconds=30)

    def check() -> HealthCheckResult:
        nonlocal calls
        calls += 1
        return HealthCheckResult("cached", HealthStatus.HEALTHY)

    checker.register("cached", check)
    checker.run_all()
    checker.run_all()
    checker.run_all(force=True)
    assert calls == 2


def test_health_checker_disposer_is_idempotent() -> None:
    checker = HealthChecker()
    dispose = checker.register("temporary", lambda: HealthCheckResult("temporary", HealthStatus.HEALTHY))
    dispose()
    dispose()
    assert checker.component("temporary") is None


def test_health_checker_http_api_and_static_ui(tmp_path) -> None:
    from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
    from test_desktop_http import _runtime

    app = create_desktop_app(_runtime(tmp_path))
    client = app.test_client()
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert "overall" in payload and "components" in payload
    assert client.post("/api/health/run").status_code == 200
    assert client.get("/api/diagnostics/benchmarks").get_json()["available"] is False
    report = client.get("/api/diagnostics/report")
    assert report.status_code == 200
    assert report.get_json()["format"] == "offline-companion-diagnostics"
    assert client.get("/api/health/missing").status_code == 404


def test_health_ui_contains_refresh_controls() -> None:
    from pathlib import Path

    root = Path(__file__).parents[1]
    html = (root / "src/offline_companion/shell/ui_host/desktop/static/index.html").read_text(encoding="utf-8")
    javascript = (root / "src/offline_companion/shell/ui_host/desktop/static/shell_api.js").read_text(encoding="utf-8")
    assert "系统诊断" in html
    assert "healthRefresh" in html
    assert "/api/health" in javascript
    assert "loadHealthStatus" in javascript
