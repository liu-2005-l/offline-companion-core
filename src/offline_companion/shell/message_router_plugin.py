"""MessageRouter 的 PluginFiber 工厂适配。"""

from __future__ import annotations

from typing import Any

from offline_companion.shell.message_router import MessageRouter


def create_plugin(context: Any) -> MessageRouter:
    """摘要：创建并托管 MessageRouter。

    参数：
        context: PluginContext，支持可选的 ``sqlite`` 服务。
    返回值：
        已注册清理 disposer 的 MessageRouter。
    """
    router = MessageRouter(context.services.get("sqlite"))
    context.effect.add_disposer(router.close)
    return router
