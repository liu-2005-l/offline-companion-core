from __future__ import annotations

from pathlib import Path

from offline_companion.core.plan_orchestrator import PlanOrchestrator
from offline_companion.core.state_manager import StateManager
from offline_companion.shell.auto_router import AutoRouter, RoutingContext, RoutingMode
from offline_companion.shell.plan_auto_bridge import PlanAutoBridge
from offline_companion.shared.messages import BaseMessage


def test_plan_auto_bridge_persists_route_decision(tmp_path: Path) -> None:
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
        lambda message: RoutingContext(query=message.topic, privacy_mode="local_only", metadata={"requires_consent": True}),
    )

    message = BaseMessage(message_id="m-1", topic="task.demo", source="shell")
    context = bridge.execute(message, plan_id="demo", invoke_skill=lambda step, ctx: True)

    assert context.state["route_decision"]["mode"] == RoutingMode.LOCAL.value
    assert context.state["requires_consent"] is True
    assert sm.get_route_state("demo")["mode"] == RoutingMode.LOCAL.value


def test_plan_auto_bridge_promotes_requires_consent_into_step(tmp_path: Path) -> None:
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
        lambda message: RoutingContext(query=message.topic, privacy_mode="local_only", metadata={"requires_consent": True}),
    )

    message = BaseMessage(message_id="m-1", topic="task.demo", source="shell")
    context = bridge.execute(message, plan_id="demo", invoke_skill=lambda step, ctx: True)

    assert context.steps["step-1"].require_consent is True
