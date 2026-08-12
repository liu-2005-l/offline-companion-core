from __future__ import annotations

from unittest.mock import Mock

import pytest

from offline_companion.core.attention_awareness import (
    AttentionContext,
    AttentionGuard,
    AttentionGuardConfig,
)
from offline_companion.core.goal_manager import GoalEvaluator, GoalManager, analyze_feedback
from offline_companion.shared.types import FeedbackLevel, ReminderCandidate

NOW = 2_000_000_000.0


@pytest.mark.parametrize(
    ("reply", "level"),
    [
        ("别再提醒我了", FeedbackLevel.STRONG_NEGATIVE.value),
        ("知道了", FeedbackLevel.WEAK_NEGATIVE.value),
        ("谢谢提醒", FeedbackLevel.POSITIVE.value),
        ("今天天气不错", None),
        ("", None),
    ],
)
def test_analyze_feedback(reply: str, level: str | None) -> None:
    assert analyze_feedback(reply).level == level


def test_goal_manager_evaluates_and_classifies_candidates() -> None:
    show = ReminderCandidate("1", "展示", 0.8, "原因", "normal", None, 0.0, 1.0)
    silent = ReminderCandidate("2", "静默", 0.2, "原因", "normal", None, 0.0, 1.0)
    evaluator = Mock(spec=GoalEvaluator)
    evaluator.evaluate.return_value = [show, silent]
    manager = GoalManager(
        Mock(),
        evaluator,
        AttentionGuard(AttentionGuardConfig(night_start_hour=0, night_end_hour=0)),
    )
    context = AttentionContext()

    decision = manager.evaluate_reminders(context, now=NOW)

    assert decision.candidates_to_show == [show]
    assert decision.candidates_silent == [silent]
    assert decision.context is context
    evaluator.evaluate.assert_called_once_with(now=NOW)


def test_goal_manager_records_shown_and_feedback() -> None:
    repository = Mock()
    guard = Mock()
    manager = GoalManager(repository, Mock(), guard)

    manager.record_reminder_shown("1", now=NOW)
    level = manager.record_user_feedback("1", "别再提醒")

    repository.record_reminder.assert_called_once_with("1")
    guard.record_shown.assert_called_once_with(now=NOW)
    repository.record_feedback.assert_called_once_with("1", FeedbackLevel.STRONG_NEGATIVE.value)
    assert level == FeedbackLevel.STRONG_NEGATIVE.value
