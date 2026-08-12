"""GoalManager 评估器：遍历活动目标，计算效用分并输出提醒候选。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from offline_companion.core.goal_manager.repository import GoalRepository
from offline_companion.shared.types import Goal, GoalPriority, ReminderCandidate

_PRIORITY_WEIGHTS = {
    GoalPriority.NORMAL.value: 0.3,
    GoalPriority.HIGH.value: 0.6,
    GoalPriority.URGENT.value: 0.9,
}


@dataclass
class GoalEvaluatorConfig:
    """摘要：目标评估器的可调参数，支持注入时间以便确定性测试。"""

    reminder_cooldown_hours: float = 4.0
    daily_reminder_cap: int = 2
    deadline_urgent_hours: float = 24.0
    deadline_warn_hours: float = 72.0
    stale_progress_hours: float = 48.0
    negative_decay_per_day: float = 0.3
    now: float | None = None


class GoalEvaluator:
    """摘要：评估活动目标并按效用分降序返回提醒候选。"""

    def __init__(self, repository: GoalRepository, config: GoalEvaluatorConfig | None = None) -> None:
        self._repo = repository
        self._cfg = config or GoalEvaluatorConfig()

    def evaluate(self, now: float | None = None) -> list[ReminderCandidate]:
        """摘要：纯读取评估活动目标，不记录实际提醒行为。"""
        timestamp = now if now is not None else (self._cfg.now if self._cfg.now is not None else time.time())
        candidates: list[ReminderCandidate] = []
        for goal in self._repo.list_active():
            if self._repo.is_suppressed(goal.goal_id):
                continue
            if self._in_cooldown(goal, timestamp) or self._exceeds_daily_cap(goal, timestamp):
                continue
            candidate = self._evaluate_single(goal, timestamp)
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(key=lambda candidate: candidate.urgency, reverse=True)
        return candidates

    def _evaluate_single(self, goal: Goal, now: float) -> ReminderCandidate | None:
        """摘要：计算单个目标的效用分与可读触发原因。"""
        reasons: list[str] = []
        score = _PRIORITY_WEIGHTS.get(goal.priority, _PRIORITY_WEIGHTS[GoalPriority.NORMAL.value])
        if goal.priority == GoalPriority.URGENT.value:
            reasons.append("用户标记紧急")

        if goal.deadline is not None:
            hours_left = (goal.deadline - now) / 3600.0
            if hours_left <= 0:
                score += 0.4
                reasons.append("已过截止时间")
            elif hours_left <= self._cfg.deadline_urgent_hours:
                score += 0.3
                reasons.append(f"截止时间临近（{hours_left:.0f}h）")
            elif hours_left <= self._cfg.deadline_warn_hours:
                score += 0.15
                reasons.append(f"截止时间接近（{hours_left:.0f}h）")

        hours_since_update = (now - goal.updated_at) / 3600.0
        if hours_since_update >= self._cfg.stale_progress_hours and goal.progress < 1.0:
            score += 0.15
            reasons.append("进度停滞")

        days_since_last = self._days_since_last_reminder(goal, now)
        effective_negative_score = max(
            0.0,
            goal.negative_feedback_score - days_since_last * self._cfg.negative_decay_per_day,
        )
        score -= effective_negative_score * 0.2

        if goal.last_reminder_at is None:
            score += 0.15
            reasons.append("从未提醒")
        elif now - goal.last_reminder_at >= 86400.0:
            score += 0.1
            reasons.append("超过一天未提醒")

        urgency = max(0.0, min(1.0, score))
        if urgency < 0.2:
            return None
        return ReminderCandidate(
            goal_id=goal.goal_id,
            description=goal.description,
            urgency=urgency,
            reason="；".join(reasons) if reasons else "常规提醒",
            priority=goal.priority,
            deadline=goal.deadline,
            progress=goal.progress,
            days_since_last_reminder=days_since_last,
        )

    def _in_cooldown(self, goal: Goal, now: float) -> bool:
        """摘要：判断目标是否仍处于提醒冷却期。"""
        if goal.last_reminder_at is None:
            return False
        return (now - goal.last_reminder_at) / 3600.0 < self._cfg.reminder_cooldown_hours

    def _exceeds_daily_cap(self, goal: Goal, now: float) -> bool:
        """摘要：按提醒历史精确执行最近二十四小时提醒上限。"""
        return self._repo.get_reminder_count_today(goal.goal_id, now) >= self._cfg.daily_reminder_cap

    @staticmethod
    def _days_since_last_reminder(goal: Goal, now: float) -> float:
        """摘要：返回距上次提醒的天数；从未提醒时返回正无穷。"""
        if goal.last_reminder_at is None:
            return float("inf")
        return (now - goal.last_reminder_at) / 86400.0
