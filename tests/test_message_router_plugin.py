"""MessageRouter 生命周期工厂测试。"""

import asyncio

from offline_companion.core.lifecycle import EffectScope, PluginContext
from offline_companion.shell.message_router_plugin import create_plugin


def test_message_router_plugin_registers_close_disposer() -> None:
    context = PluginContext(
        plugin_id="message-router",
        config={},
        services={},
        effect=EffectScope("message-router"),
        event_stream=None,
        logger=None,
    )
    router = create_plugin(context)
    router.register("demo", lambda _message: "ok")

    asyncio.run(context.effect.dispose())

    assert router._handlers == {}
    assert router._wildcard_handler is None
