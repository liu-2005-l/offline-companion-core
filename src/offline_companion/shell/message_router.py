"""message_router：A/B/C 层消息路由骨架。"""

from __future__ import annotations

from collections.abc import Callable

from offline_companion.shared.messages import BaseMessage, MessageLayer

MessageHandler = Callable[[BaseMessage], None]


class MessageRouter:
    """摘要：按 topic 前缀分发消息的最小路由器。"""

    def __init__(self) -> None:
        self._handlers: dict[str, MessageHandler] = {}

    def register(self, namespace: str, handler: MessageHandler) -> None:
        key = (namespace or "").strip()
        if not key:
            raise ValueError("namespace 不能为空")
        if "." in key or key == "*":
            raise ValueError("namespace 必须为单段命名空间，且不能为通配符")
        self._handlers[key] = handler

    def register_wildcard(self, handler: MessageHandler) -> None:
        """摘要：注册兜底处理器，仅允许一个。"""
        self._handlers["*"] = handler

    def route(self, message: BaseMessage) -> None:
        namespace = message.namespace().strip()
        if not namespace:
            raise ValueError("消息 topic 不能为空")
        if message.source != MessageLayer.SHELL.value and namespace == "shell":
            raise ValueError("shell 命名空间消息必须由 shell 层发出")
        handler = self._handlers.get(namespace)
        if handler is None:
            handler = self._handlers.get("*")
        if handler is None:
            raise KeyError(f"未找到消息处理器: {message.topic!r}")
        handler(message)
