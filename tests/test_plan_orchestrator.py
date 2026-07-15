from __future__ import annotations

import json
from pathlib import Path

from offline_companion.core.plan_orchestrator import PlanOrchestrator
from offline_companion.core.state_manager import StateManager


def test_plan_orchestrator_runs_template_steps(tmp_path: Path) -> None:
    templates_dir = tmp_path / "plans"
    templates_dir.mkdir()
    (templates_dir / "demo.json").write_text(
        json.dumps(
            [
                {
                    "step_id": "step-1",
                    "skill_id": "prepare",
                    "result_key": "prepared",
                },
                {
                    "step_id": "step-2",
                    "skill_id": "finish",
                    "result_key": "finished",
                    "condition_key": "prepared",
                    "condition_value": True,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sm = StateManager(tmp_path / "state.db")
    orchestrator = PlanOrchestrator(sm, templates_dir)

    def invoke_skill(step, context):
        return True if step.skill_id == "prepare" else {"ok": True}

    context = orchestrator.execute_plan("demo", invoke_skill=invoke_skill)

    assert context.state["prepared"] is True
    assert context.state["finished"] == {"ok": True}
    assert context.state["progress"] == 1.0
    assert sm.get_task_state("plan.demo.status") == "done"
    assert sm.get_task_state("plan.demo.progress") == 1.0


def test_plan_orchestrator_skips_unmet_steps(tmp_path: Path) -> None:
    templates_dir = tmp_path / "plans"
    templates_dir.mkdir()
    (templates_dir / "skip.json").write_text(
        json.dumps(
            [
                {
                    "step_id": "step-1",
                    "skill_id": "prepare",
                    "result_key": "prepared",
                },
                {
                    "step_id": "step-2",
                    "skill_id": "finish",
                    "result_key": "finished",
                    "condition_key": "prepared",
                    "condition_value": True,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sm = StateManager(tmp_path / "state.db")
    orchestrator = PlanOrchestrator(sm, templates_dir)

    def invoke_skill(step, context):
        return False

    context = orchestrator.execute_plan("skip", invoke_skill=invoke_skill)

    assert context.state["prepared"] is False
    assert context.state["step_status"]["step-2"] == "skipped"


def test_plan_orchestrator_empty_template_marks_empty(tmp_path: Path) -> None:
    sm = StateManager(tmp_path / "state.db")
    orchestrator = PlanOrchestrator(sm, tmp_path / "plans")

    context = orchestrator.execute_plan("missing", invoke_skill=lambda step, ctx: None)

    assert context.state["status"] == "empty"
    assert sm.get_task_state("plan.missing.status") == "empty"


def test_plan_orchestrator_records_retry_and_error(tmp_path: Path) -> None:
    templates_dir = tmp_path / "plans"
    templates_dir.mkdir()
    (templates_dir / "retry.json").write_text(
        json.dumps(
            [
                {
                    "step_id": "step-1",
                    "skill_id": "prepare",
                    "result_key": "prepared",
                    "retry_count": 1,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sm = StateManager(tmp_path / "state.db")
    orchestrator = PlanOrchestrator(sm, templates_dir)
    attempts = {"count": 0}

    def invoke_skill(step, context):
        attempts["count"] += 1
        raise RuntimeError("boom")

    try:
        orchestrator.execute_plan("retry", invoke_skill=invoke_skill)
    except RuntimeError:
        pass

    assert attempts["count"] == 2
    assert sm.get_task_state("plan.retry.status") == "failed"
    assert sm.get_task_state("plan.retry.error") == "boom"
