"""GoalManager 生命周期工厂测试。"""

import asyncio

from offline_companion.core.goal_manager.plugin import create_plugin
from offline_companion.core.lifecycle import EffectScope, PluginContext


class _Resource:
    pass


def test_goal_manager_plugin_injects_dependencies_and_closes() -> None:
    context = PluginContext(
        plugin_id="goal-manager",
        config={},
        services={
            "goal-repository": _Resource(),
            "goal-evaluator": _Resource(),
            "attention-guard": _Resource(),
        },
        effect=EffectScope("goal-manager"),
        event_stream=None,
        logger=None,
    )

    manager = create_plugin(context)
    assert manager._repo is context.services["goal-repository"]

    asyncio.run(context.effect.dispose())

    assert manager._repo is None
    assert manager._evaluator is None
    assert manager._guard is None
