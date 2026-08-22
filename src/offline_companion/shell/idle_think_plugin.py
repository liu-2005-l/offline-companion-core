"""IdleThinkCoordinator 的 PluginFiber 工厂适配。"""

from __future__ import annotations

from typing import Any

from offline_companion.core.idle_think_listener import IdleThinkListener
from offline_companion.shell.idle_think_coordinator import IdleThinkCoordinator


def create_plugin(context: Any) -> IdleThinkCoordinator:
    """摘要：创建 Coordinator 并托管 StateManager listener。"""
    state_manager = context.service("state-manager")
    coordinator = IdleThinkCoordinator(
        goal_manager=context.service("goal-manager"),
        state_manager=state_manager,
        attention_context_provider=context.services.get("attention-context-provider"),
        settings_provider=context.services.get("settings-provider"),
        plan_orchestrator=context.services.get("plan-orchestrator"),
        sample_maintenance=context.services.get("sample-maintenance"),
    )
    listener = IdleThinkListener(state_manager, coordinator.on_idle)
    listener.arm()
    context.effect.add_disposer(coordinator.close)
    context.effect.add_disposer(listener.disarm)
    return coordinator
