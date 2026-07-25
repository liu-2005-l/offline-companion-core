from __future__ import annotations

from dataclasses import dataclass

from offline_companion.core.plan_orchestrator import PlanStep, StepStatus, TaskContext
from offline_companion.shell.routed_plan_invoker import (
    CloudRouteInvoker,
    EchoRouteInvoker,
    RoutedPlanInvoker,
)


@dataclass
class StubInvoker:
    calls: list[tuple[str, dict[str, object], str | None]]
    result: object

    def invoke(self, skill_id: str, payload: dict[str, object], idempotency_key: str | None = None) -> object:
        self.calls.append((skill_id, payload, idempotency_key))
        return self.result


def test_routed_plan_invoker_selects_cloud() -> None:
    local = StubInvoker([], "local")
    cloud = StubInvoker([], "cloud")
    echo = StubInvoker([], "echo")
    invoker = RoutedPlanInvoker(local, cloud, echo)
    step = PlanStep(step_id="a", skill_id="skill-x", result_key="res")
    ctx = TaskContext(plan_id="p", steps={"a": step}, step_status={"a": StepStatus.PENDING}, context_vars={"route_mode": "cloud", "fallback_chain": ["local", "cloud"]})

    result = invoker.invoke_step(step, ctx)

    assert result == "cloud"
    assert cloud.calls[0][0] == "skill-x"
    assert cloud.calls[0][1]["_route_mode"] == "cloud"


def test_routed_plan_invoker_selects_echo() -> None:
    local = StubInvoker([], "local")
    cloud = StubInvoker([], "cloud")
    echo = StubInvoker([], "echo")
    invoker = RoutedPlanInvoker(local, cloud, echo)
    step = PlanStep(step_id="a", skill_id="skill-x", result_key="res")
    ctx = TaskContext(plan_id="p", steps={"a": step}, step_status={"a": StepStatus.PENDING}, context_vars={"route_mode": "echo"})

    result = invoker.invoke_step(step, ctx)

    assert result == "echo"
    assert echo.calls[0][0] == "skill-x"


def test_cloud_route_invoker_uses_cloud_completion(monkeypatch) -> None:
    captured = {}

    class Resp:
        text = '{"ok": true}'

    def fake_post(request):
        captured["request"] = request
        return Resp()

    invoker = CloudRouteInvoker(cloud_post=fake_post)
    result = invoker.invoke("skill-x", {"a": 1}, "idem-1")

    assert result == {"ok": True}
    assert captured["request"].purpose == "plan_step_execution"


def test_echo_route_invoker_wraps_payload() -> None:
    invoker = EchoRouteInvoker()
    result = invoker.invoke("skill-x", {"a": 1}, "idem-1")

    assert result["skill_id"] == "skill-x"
    assert result["echo"]["a"] == 1
