from __future__ import annotations

from pathlib import Path

from offline_companion.core.plan_orchestrator import PlanOrchestrator
from offline_companion.core.state_manager import StateManager
from offline_companion.shell.auto_router import AutoRouter, RoutingContext, RoutingMode
from offline_companion.shell.plan_auto_bridge import PlanAutoBridge
from offline_companion.shared.messages import BaseMessage


def test_plan_auto_bridge_executes_plan_when_local(tmp_path: Path) -> None:
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "demo.json").write_text(
        """[
  {"step_id": "step-1", "skill_id": "prepare", "result_key": "prepared"}
]""",
        encoding="utf-8",
    )
    sm = StateManager(tmp_path / "state.db")
    orchestrator = PlanOrchestrator(sm, plans_dir)
    bridge = PlanAutoBridge(
        AutoRouter(),
        orchestrator,
        lambda message: RoutingContext(query=message.topic, privacy_mode="local_only"),
    )

    message = BaseMessage(message_id="m-1", topic="task.demo", source="shell")
    context = bridge.execute(message, plan_id="demo", invoke_skill=lambda step, ctx: True)

    assert context.state["auto_route"] == RoutingMode.LOCAL.value
    assert context.state["status"] == "done"


def test_plan_auto_bridge_short_circuits_echo(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    orchestrator = PlanOrchestrator(sm, tmp_path / "plans")
    bridge = PlanAutoBridge(
        AutoRouter(),
        orchestrator,
        lambda message: RoutingContext(query=message.topic, metadata={"force_echo": True}),
    )

    message = BaseMessage(message_id="m-2", topic="task.demo", source="shell")
    context = bridge.execute(message, plan_id="demo", invoke_skill=lambda step, ctx: True)

    assert context.state["auto_route"] == RoutingMode.ECHO.value
    assert context.state["plan_routed"] == "echo"
