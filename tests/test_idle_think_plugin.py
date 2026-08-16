"""IdleThink 生命周期工厂测试。"""

import asyncio

from offline_companion.core.lifecycle import EffectScope, PluginContext
from offline_companion.core.state_manager import StateManager
from offline_companion.shell.idle_think_plugin import create_plugin


class _GoalManager:
    pass


def test_idle_think_plugin_arms_listener_and_disarms_on_dispose(tmp_path) -> None:
    state_manager = StateManager(tmp_path / "state.db")
    context = PluginContext(
        plugin_id="idle-think",
        config={},
        services={"state-manager": state_manager, "goal-manager": _GoalManager()},
        effect=EffectScope("idle-think"),
        event_stream=None,
        logger=None,
    )

    coordinator = create_plugin(context)
    assert isinstance(coordinator, object)
    assert len(state_manager._subscribers) == 1

    asyncio.run(context.effect.dispose())

    assert state_manager._subscribers == {}
