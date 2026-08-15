"""多事件流的生命周期管理。"""

from __future__ import annotations

import threading

from .registry import EventTypeRegistry
from .stream import EventStream


class StreamManager:
    """按 stream_id 管理多个独立事件流。

    参数：
        registry: 各事件流共享的事件类型注册表。
    """

    def __init__(self, registry: EventTypeRegistry) -> None:
        self._registry = registry
        self._streams: dict[str, EventStream] = {}
        self._lock = threading.Lock()

    def get_or_create(self, stream_id: str) -> EventStream:
        """获取指定事件流，不存在时创建。"""
        with self._lock:
            if stream_id not in self._streams:
                self._streams[stream_id] = EventStream(stream_id, self._registry)
            return self._streams[stream_id]

    def get(self, stream_id: str) -> EventStream | None:
        """获取已存在的事件流，不创建新流。"""
        with self._lock:
            return self._streams.get(stream_id)
