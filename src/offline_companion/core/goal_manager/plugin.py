"""GoalManager 的 PluginFiber 工厂适配。"""

from __future__ import annotations

from typing import Any

from offline_companion.core.goal_manager.manager import GoalManager


def create_plugin(context: Any) -> GoalManager:
    """摘要：从生命周期服务快照创建并托管 GoalManager。"""
    manager = GoalManager(
        context.service("goal-repository"),
        context.service("goal-evaluator"),
        context.service("attention-guard"),
    )
    context.effect.add_disposer(manager.close)
    return manager
