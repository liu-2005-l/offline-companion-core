from __future__ import annotations

from dataclasses import replace

import pytest

from offline_companion.core.goal_manager import GoalEvaluator, GoalEvaluatorConfig
from offline_companion.shared.types import Goal, GoalPriority

NOW = 2_000_000_000.0


class FakeGoalRepository:
    def __init__(self, goals: list[Goal], suppressed: set[str] | None = None) -> None:
        self.goals = goals
        self.suppressed = suppressed or set()

    def list_active(self) -> list[Goal]:
        return list(self.goals)

    def is_suppressed(self, goal_id: str) -> bool:
        return goal_id in self.suppressed

    def get_reminder_count_today(self, goal_id: str, now: float) -> int:
        goal = next(goal for goal in self.goals if goal.goal_id == goal_id)
        if goal.last_reminder_at is None or now - goal.last_reminder_at >= 86400.0:
            return 0
        return goal.reminder_count


def _goal(**changes: object) -> Goal:
    goal = Goal(
        goal_id="1",
        description="完成版本发布",
        goal_status="active",
        priority=GoalPriority.NORMAL.value,
        progress=0.0,
        created_at=NOW - 3600.0,
        updated_at=NOW - 3600.0,
        deadline=None,
        reminder_count=0,
        last_reminder_at=None,
        negative_feedback_score=0.0,
        tags=[],
    )
    return replace(goal, **changes)


def _evaluate(goals: list[Goal], **config: object):
    repository = FakeGoalRepository(goals)
    return GoalEvaluator(repository, GoalEvaluatorConfig(now=NOW, **config)).evaluate()


def test_empty_and_never_reminded_goal() -> None:
    assert _evaluate([]) == []
    candidate = _evaluate([_goal()])[0]
    assert candidate.urgency == pytest.approx(0.45)
    assert candidate.days_since_last_reminder == float("inf")
    assert "从未提醒" in candidate.reason


def test_cooldown_and_daily_cap_filters() -> None:
    recent = _goal(last_reminder_at=NOW - 3 * 3600.0, reminder_count=1)
    assert _evaluate([recent]) == []

    cap_reached = replace(recent, last_reminder_at=NOW - 5 * 3600.0, reminder_count=2)
    assert _evaluate([cap_reached]) == []

    next_day = replace(recent, last_reminder_at=NOW - 25 * 3600.0, reminder_count=20)
    assert _evaluate([next_day])[0].urgency == pytest.approx(0.4)


def test_suppressed_goal_is_filtered() -> None:
    repository = FakeGoalRepository([_goal()], {"1"})
    assert GoalEvaluator(repository, GoalEvaluatorConfig(now=NOW)).evaluate() == []


@pytest.mark.parametrize(
    ("hours_left", "bonus", "reason"),
    [(-1.0, 0.4, "已过截止时间"), (12.0, 0.3, "截止时间临近"), (48.0, 0.15, "截止时间接近")],
)
def test_deadline_bonuses(hours_left: float, bonus: float, reason: str) -> None:
    candidate = _evaluate([_goal(deadline=NOW + hours_left * 3600.0)])[0]
    assert candidate.urgency == pytest.approx(0.45 + bonus)
    assert reason in candidate.reason


def test_stale_progress_bonus() -> None:
    candidate = _evaluate([_goal(updated_at=NOW - 48 * 3600.0)])[0]
    assert candidate.urgency == pytest.approx(0.6)
    assert "进度停滞" in candidate.reason


def test_negative_feedback_penalty_decays() -> None:
    config = {"reminder_cooldown_hours": 0.0, "daily_reminder_cap": 99}
    recent = _goal(
        priority=GoalPriority.HIGH.value,
        last_reminder_at=NOW,
        negative_feedback_score=1.0,
    )
    old = replace(recent, goal_id="2", last_reminder_at=NOW - 2 * 86400.0)
    recent_candidate = _evaluate([recent], **config)[0]
    old_candidate = _evaluate([old], **config)[0]
    assert recent_candidate.urgency == pytest.approx(0.4)
    assert old_candidate.urgency == pytest.approx(0.62)


def test_low_urgency_is_filtered() -> None:
    goal = _goal(last_reminder_at=NOW, negative_feedback_score=1.0)
    assert _evaluate([goal], reminder_cooldown_hours=0.0, daily_reminder_cap=99) == []


def test_results_sorted_and_urgent_reason() -> None:
    normal = _goal(goal_id="normal")
    urgent = _goal(goal_id="urgent", priority=GoalPriority.URGENT.value)
    candidates = _evaluate([normal, urgent])
    assert [candidate.goal_id for candidate in candidates] == ["urgent", "normal"]
    assert candidates[0].urgency == 1.0
    assert "用户标记紧急" in candidates[0].reason


def test_explicit_now_overrides_config_and_has_no_side_effects() -> None:
    goal = _goal(last_reminder_at=NOW - 5 * 3600.0, reminder_count=1)
    repository = FakeGoalRepository([goal])
    evaluator = GoalEvaluator(repository, GoalEvaluatorConfig(now=NOW - 3 * 3600.0))

    assert evaluator.evaluate() == []
    assert evaluator.evaluate(now=NOW)
    assert repository.goals[0].reminder_count == 1
