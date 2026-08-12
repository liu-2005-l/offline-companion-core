from __future__ import annotations

import json

import pytest

from offline_companion.core.goal_manager import GoalRepository
from offline_companion.runtime.storage_index.engine import connect
from offline_companion.shared.types import FeedbackLevel, GoalPriority, GoalStatus


def _repository(tmp_path) -> tuple[GoalRepository, object]:
    conn = connect(tmp_path / "goals.db")
    return GoalRepository(conn), conn


def test_create_and_get_goal(tmp_path) -> None:
    repository, conn = _repository(tmp_path)
    goal_id = repository.create(
        "每天学习 Python",
        priority=GoalPriority.HIGH.value,
        deadline=2_000_000_000,
        tags=["学习", "Python", "学习"],
    )

    goal = repository.get(goal_id)
    row = conn.execute("SELECT memory_type, status, source, metadata FROM memory_chunks WHERE id = ?;", (int(goal_id),)).fetchone()

    assert isinstance(goal_id, str)
    assert goal is not None
    assert goal.description == "每天学习 Python"
    assert goal.priority == GoalPriority.HIGH.value
    assert goal.tags == ["学习", "Python"]
    assert row["memory_type"] == "goal"
    assert row["status"] == "active"
    assert row["source"] == "user_explicit"
    assert json.loads(row["metadata"])["progress"] == 0.0


def test_create_rejects_empty_urgent_and_invalid_priority(tmp_path) -> None:
    repository, _conn = _repository(tmp_path)
    with pytest.raises(ValueError, match="description"):
        repository.create("  ")
    with pytest.raises(ValueError, match="urgent"):
        repository.create("目标", priority=GoalPriority.URGENT.value)
    with pytest.raises(ValueError, match="priority"):
        repository.create("目标", priority="critical")


def test_get_missing_and_invalid_goal_id(tmp_path) -> None:
    repository, _conn = _repository(tmp_path)
    assert repository.get("999") is None
    with pytest.raises(ValueError, match="invalid goal id"):
        repository.get("not-an-id")


def test_progress_completion_and_active_filter(tmp_path) -> None:
    repository, conn = _repository(tmp_path)
    active_id = repository.create("活动目标")
    completed_id = repository.create("完成目标")

    repository.update_progress(active_id, 0.5)
    repository.update_progress(completed_id, 1.0)

    assert repository.get(active_id).progress == 0.5
    completed = repository.get(completed_id)
    assert completed is not None
    assert completed.goal_status == GoalStatus.COMPLETED.value
    assert [goal.goal_id for goal in repository.list_active()] == [active_id]
    status = conn.execute("SELECT status FROM memory_chunks WHERE id = ?;", (int(completed_id),)).fetchone()[0]
    assert status == "cancelled"
    with pytest.raises(ValueError, match="progress"):
        repository.update_progress(active_id, 1.1)


def test_priority_reminder_and_metadata_updates_preserve_fields(tmp_path) -> None:
    repository, _conn = _repository(tmp_path)
    goal_id = repository.create("紧急目标", tags=["保留"])

    repository.update_priority(goal_id, GoalPriority.URGENT.value)
    repository.record_reminder(goal_id)
    repository.record_reminder(goal_id)

    goal = repository.get(goal_id)
    assert goal is not None
    assert goal.priority == GoalPriority.URGENT.value
    assert goal.reminder_count == 2
    assert goal.last_reminder_at is not None
    assert goal.tags == ["保留"]
    with pytest.raises(ValueError, match="priority"):
        repository.update_priority(goal_id, "critical")


def test_feedback_accumulates_and_never_goes_negative(tmp_path) -> None:
    repository, _conn = _repository(tmp_path)
    goal_id = repository.create("反馈目标")

    repository.record_feedback(goal_id, FeedbackLevel.POSITIVE.value)
    assert repository.get(goal_id).negative_feedback_score == 0.0
    repository.record_feedback(goal_id, FeedbackLevel.WEAK_NEGATIVE.value)
    repository.record_feedback(goal_id, FeedbackLevel.STRONG_NEGATIVE.value)
    assert repository.get(goal_id).negative_feedback_score == pytest.approx(1.3)
    assert not repository.is_suppressed(goal_id)
    repository.record_feedback(goal_id, FeedbackLevel.STRONG_NEGATIVE.value)
    assert repository.is_suppressed(goal_id)
    with pytest.raises(ValueError, match="feedback"):
        repository.record_feedback(goal_id, "unknown")


def test_deactivate_completed_and_abandoned(tmp_path) -> None:
    repository, conn = _repository(tmp_path)
    completed_id = repository.create("完成")
    abandoned_id = repository.create("放弃")

    repository.deactivate(completed_id)
    repository.deactivate(abandoned_id, GoalStatus.ABANDONED.value)

    assert repository.get(completed_id).goal_status == GoalStatus.COMPLETED.value
    assert repository.get(abandoned_id).goal_status == GoalStatus.ABANDONED.value
    statuses = conn.execute(
        "SELECT status FROM memory_chunks WHERE id IN (?, ?) ORDER BY id;",
        (int(completed_id), int(abandoned_id)),
    ).fetchall()
    assert [row["status"] for row in statuses] == ["cancelled", "cancelled"]
    assert repository.list_active() == []
    with pytest.raises(ValueError, match="reason"):
        repository.deactivate(completed_id, "paused")


def test_mutations_reject_non_goal_rows(tmp_path) -> None:
    repository, conn = _repository(tmp_path)
    conn.execute(
        "INSERT INTO memory_chunks(content, body, memory_type, status, source, created_at, modified_at) "
        "VALUES('fact', 'fact', 'fact', 'active', 'user_explicit', 0, 0);"
    )
    fact_id = str(conn.execute("SELECT last_insert_rowid();").fetchone()[0])

    with pytest.raises(ValueError, match="not found"):
        repository.record_reminder(fact_id)


def test_reminder_history_counts_last_day_and_prunes_old_entries(tmp_path, monkeypatch) -> None:
    repository, conn = _repository(tmp_path)
    goal_id = repository.create("提醒历史")
    now = 2_000_000_000.0
    metadata = json.loads(conn.execute("SELECT metadata FROM memory_chunks WHERE id = ?", (int(goal_id),)).fetchone()[0])
    metadata["reminder_history"] = [now - 8 * 86400.0, now - 3600.0, "invalid"]
    conn.execute(
        "UPDATE memory_chunks SET metadata = ? WHERE id = ?",
        (json.dumps(metadata), int(goal_id)),
    )
    monkeypatch.setattr("offline_companion.core.goal_manager.repository.time.time", lambda: now)

    repository.record_reminder(goal_id)

    assert repository.get_reminder_count_today(goal_id, now) == 2
    stored = json.loads(conn.execute("SELECT metadata FROM memory_chunks WHERE id = ?", (int(goal_id),)).fetchone()[0])
    assert stored["reminder_history"] == [now - 3600.0, now]
    assert repository.get_reminder_count_today("999", now) == 0
