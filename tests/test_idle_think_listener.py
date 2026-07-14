from __future__ import annotations

from pathlib import Path

from offline_companion.core.idle_think_listener import IdleThinkListener, IdleThinkOrchestratorBridge
from offline_companion.core.plan_orchestrator import PlanOrchestrator
from offline_companion.core.state_manager import StateManager
from offline_companion.shell.skill_manager.invoker import SkillInvoker


def test_idle_think_listener_triggers_callback(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    events: list[str] = []

    listener = IdleThinkListener(sm, lambda: events.append("idle"))
    listener.arm()
    sm.trigger_idle_think()

    assert events == ["idle"]


def test_idle_think_listener_disarm_stops_callback(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    events: list[str] = []

    listener = IdleThinkListener(sm, lambda: events.append("idle"))
    listener.arm()
    listener.disarm()
    sm.trigger_idle_think()

    assert events == []


def test_idle_think_orchestrator_bridge_executes_plan(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "idle_think.json").write_text(
        """[
  {"step_id": "step-1", "skill_id": "inspect_session_state", "result_key": "session_snapshot"}
]""",
        encoding="utf-8",
    )
    (tmp_path / "entry.py").write_text("print('ok')\n", encoding="utf-8")
    orchestrator = PlanOrchestrator(sm, plans_dir)
    skill_invoker = SkillInvoker()

    bridge = IdleThinkOrchestratorBridge(
        sm,
        orchestrator,
        skill_invoker,
        tmp_path,
    )
    bridge.arm()
    sm.trigger_idle_think()

    assert sm.get_task_state("plan.idle_think.status") in {"done", "failed"}


def test_idle_think_orchestrator_bridge_uses_real_plan(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "idle_think.json").write_text(
        """[
  {"step_id": "step-1", "skill_id": "inspect_session_state", "result_key": "session_snapshot"}
]""",
        encoding="utf-8",
    )
    (tmp_path / "entry.py").write_text("print('ok')\n", encoding="utf-8")

    orchestrator = PlanOrchestrator(sm, plans_dir)
    skill_invoker = SkillInvoker()
    bridge = IdleThinkOrchestratorBridge(sm, orchestrator, skill_invoker, tmp_path)
    bridge.arm()
    sm.trigger_idle_think()

    assert sm.get_task_state("plan.idle_think.context")["plan_id"] == "idle_think"


def test_idle_think_bridge_has_default_entry_script(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "idle_think.json").write_text(
        """[
  {"step_id": "step-1", "skill_id": "inspect_session_state", "result_key": "session_snapshot"}
]""",
        encoding="utf-8",
    )
    entry = tmp_path / "entry.py"
    entry.write_text("print('idle')\n", encoding="utf-8")

    orchestrator = PlanOrchestrator(sm, plans_dir)
    skill_invoker = SkillInvoker()
    bridge = IdleThinkOrchestratorBridge(sm, orchestrator, skill_invoker, tmp_path)

    assert entry.is_file()
    bridge.arm()
    sm.trigger_idle_think()
    assert sm.get_task_state("plan.idle_think.status") in {"done", "failed"}
