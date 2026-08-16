"""GoalManager 门面：串联目标评估、注意力闸门和反馈记录。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from offline_companion.core.attention_awareness import AttentionContext, AttentionGuard, QuietLevel
from offline_companion.core.goal_manager.evaluator import GoalEvaluator
from offline_companion.core.goal_manager.repository import GoalRepository
from offline_companion.core.goal_manager.semantic_feedback import analyze_feedback
from offline_companion.shared.types import ReminderCandidate


@dataclass(frozen=True)
class ReminderDecision:
    """摘要：注意力闸门处理后的最终提醒决策。"""

    candidates_to_show: list[ReminderCandidate]
    candidates_silent: list[ReminderCandidate]
    context: AttentionContext


class GoalManager:
    """摘要：串联 GoalEvaluator 与 AttentionGuard 的被动提醒决策入口。"""

    def __init__(
        self,
        repository: GoalRepository,
        evaluator: GoalEvaluator,
        guard: AttentionGuard,
    ) -> None:
        self._repo = repository
        self._evaluator = evaluator
        self._guard = guard

    def evaluate_reminders(
        self,
        context: AttentionContext,
        now: float | None = None,
    ) -> ReminderDecision:
        """摘要：依次评估目标、过滤候选并分类展示与静默结果。"""
        timestamp = now if now is not None else time.time()
        filtered = self._guard.filter(self._evaluator.evaluate(now=timestamp), context, now=timestamp)
        candidates_to_show = [candidate for candidate, level in filtered if level == QuietLevel.ALLOW]
        candidates_silent = [candidate for candidate, level in filtered if level == QuietLevel.SILENT]
        return ReminderDecision(
            candidates_to_show=candidates_to_show,
            candidates_silent=candidates_silent,
            context=context,
        )

    def record_reminder_shown(self, goal_id: str, now: float | None = None) -> None:
        """摘要：在提醒实际展示后记录目标历史与全局频率。"""
        self._repo.record_reminder(goal_id)
        self._guard.record_shown(now=now)

    def record_user_feedback(self, goal_id: str, user_reply: str, now: float | None = None) -> str | None:
        """摘要：分析用户回复并将识别出的反馈级别写入目标仓库。"""
        del now
        result = analyze_feedback(user_reply)
        if result.level is not None:
            self._repo.record_feedback(goal_id, result.level)
        return result.level

    def close(self) -> None:
        """摘要：释放 GoalManager 对目标评估资源的引用。"""
        self._repo = None
        self._evaluator = None
        self._guard = None
