"""goal_manager：长期目标管理与提醒决策（A2 控制面）。"""

from offline_companion.core.goal_manager.evaluator import GoalEvaluator, GoalEvaluatorConfig
from offline_companion.core.goal_manager.manager import GoalManager, ReminderDecision
from offline_companion.core.goal_manager.repository import GoalRepository
from offline_companion.core.goal_manager.semantic_feedback import (
    SemanticFeedbackResult,
    analyze_feedback,
)

__all__ = [
    "GoalEvaluator",
    "GoalEvaluatorConfig",
    "GoalManager",
    "GoalRepository",
    "ReminderDecision",
    "SemanticFeedbackResult",
    "analyze_feedback",
]
