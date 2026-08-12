from __future__ import annotations

from offline_companion.core.plan_orchestrator import (
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
    StepStatus,
)
from offline_companion.core.state_manager import StateManager


def _orchestrator(db_path) -> PlanOrchestrator:
    return PlanOrchestrator(
        StateManager(db_path),
        skill_invoker=lambda skill_id, payload, idempotency_key: f"done:{skill_id}",
    )


def test_restart_restores_paused_plan_snapshot(tmp_path) -> None:
    """摘要：重建 StateManager 与编排器后恢复等待同意的完整计划快照。"""
    db_path = tmp_path / "state.db"
    first = _orchestrator(db_path)
    steps = [
        PlanStep(step_id="done", skill_id="local", result_key="local_result"),
        PlanStep(
            step_id="waiting",
            skill_id="cloud",
            result_key="cloud_result",
            depends_on=("done",),
            require_consent=True,
        ),
        PlanStep(
            step_id="pending",
            skill_id="local",
            result_key="final_result",
            depends_on=("waiting",),
        ),
    ]

    paused = first.start("restart-plan", steps)
    assert paused.status is PlanStatus.PAUSED

    restored = _orchestrator(db_path).load_context("restart-plan")

    assert restored is not None
    assert restored.status is PlanStatus.PAUSED
    assert restored.step_status == {
        "done": StepStatus.DONE,
        "waiting": StepStatus.BLOCKED,
        "pending": StepStatus.PENDING,
    }
    assert restored.step_results["local_result"] == "done:local"
    assert restored.paused_step_id == "waiting"


def test_restart_restores_terminal_plan_states(tmp_path) -> None:
    """摘要：完成和取消状态均通过 SQLite 在编排器重建后保留。"""
    db_path = tmp_path / "state.db"
    first = _orchestrator(db_path)
    completed = first.start(
        "completed-plan",
        [PlanStep(step_id="only", skill_id="local", result_key="result")],
    )
    first.start(
        "cancelled-plan",
        [PlanStep(step_id="waiting", skill_id="cloud", result_key="result", require_consent=True)],
    )
    first.cancel("cancelled-plan")

    restarted = _orchestrator(db_path)

    assert completed.status is PlanStatus.DONE
    assert restarted.load_context("completed-plan").status is PlanStatus.DONE
    assert restarted.load_context("cancelled-plan").status is PlanStatus.CANCELLED


def test_clean_store_returns_no_context(tmp_path) -> None:
    """摘要：空数据库读取未知计划时安全返回 None。"""
    assert _orchestrator(tmp_path / "state.db").load_context("missing") is None
