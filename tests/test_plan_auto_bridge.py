from __future__ import annotations

from pathlib import Path

from offline_companion.core.plan_orchestrator import PlanOrchestrator
from offline_companion.core.state_manager import StateManager
from offline_companion.shared.messages import BaseMessage
from offline_companion.shell.auto_router import (
    AutoRouter,
    RoutingContext,
    RoutingDecision,
    RoutingMode,
)
from offline_companion.shell.plan_auto_bridge import PlanAutoBridge


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


def test_plan_auto_bridge_routes_each_step_independently(tmp_path: Path) -> None:
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "demo.json").write_text(
        """[
  {"step_id": "local", "skill_id": "prepare", "result_key": "prepared", "payload": {"description": "local work"}},
  {"step_id": "cloud", "skill_id": "research", "result_key": "researched", "depends_on": ["local"], "payload": {"description": "remote work"}}
]""",
        encoding="utf-8",
    )

    class StepAdvisor:
        def advise(self, context, candidates):
            mode = RoutingMode.CLOUD if "remote" in context.query else RoutingMode.LOCAL
            return RoutingDecision(mode=mode, reason=f"step:{context.query}", selected_by="test")

    sm = StateManager(tmp_path / "state.db")
    orchestrator = PlanOrchestrator(sm, plans_dir)
    bridge = PlanAutoBridge(
        AutoRouter(advisor=StepAdvisor()),
        orchestrator,
        lambda message: RoutingContext(query=message.topic, privacy_mode="hybrid"),
    )

    context = bridge.execute(
        BaseMessage(message_id="m-1", topic="task.demo", source="shell"),
        plan_id="demo",
        invoke_skill=lambda step, ctx: step.step_id,
    )

    assert context.get_step_route_decision("local")["mode"] == RoutingMode.LOCAL.value
    assert context.get_step_route_decision("cloud")["mode"] == RoutingMode.CLOUD.value


def test_plan_auto_bridge_prepare_does_not_execute(tmp_path: Path) -> None:
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "demo.json").write_text(
        '[{"step_id":"step-1","skill_id":"prepare","result_key":"prepared"}]',
        encoding="utf-8",
    )
    orchestrator = PlanOrchestrator(StateManager(tmp_path / "state.db"), plans_dir)
    bridge = PlanAutoBridge(
        AutoRouter(),
        orchestrator,
        lambda message: RoutingContext(query=message.topic, privacy_mode="local_only"),
    )

    context = bridge.prepare(
        BaseMessage(message_id="m-1", topic="task.demo", source="shell"),
        plan_id="demo",
    )

    assert context.step_results == {}
    assert context.get_step_route_decision("step-1")["mode"] == RoutingMode.LOCAL.value
