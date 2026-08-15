"""内存事件流及其 append 提交边界。"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from .registry import EventTypeRegistry
from .types import DomainEvent

logger = logging.getLogger(__name__)


class EventStream:
    """维护单个 stream 的不可变事件序列。

    参数：
        stream_id: 事件流标识。
        registry: 事件类型注册表。
    """

    def __init__(self, stream_id: str, registry: EventTypeRegistry) -> None:
        self._stream_id = stream_id
        self._registry = registry
        self._events: list[DomainEvent] = []
        self._observers: list[Callable[[DomainEvent], None]] = []
        self._lock = threading.Lock()
        self._notification_state = threading.local()

    @property
    def stream_id(self) -> str:
        """返回事件流标识。"""
        return self._stream_id

    @property
    def latest_seq(self) -> int:
        """返回当前事件流的最后序号；空流返回 -1。"""
        with self._lock:
            return len(self._events) - 1

    def append(self, event_type: str, payload: dict[str, Any]) -> DomainEvent:
        """校验并提交事件，然后通知 observer。

        参数：
            event_type: 已注册的事件类型。
            payload: JSON 可序列化的字典负载。

        返回值：
            已提交的不可变领域事件。

        Raises:
            RuntimeError: observer 内尝试重入当前事件流。
            TypeError: payload 不是字典。
            ValueError: 事件类型未注册或 payload 不可序列化。
        """
        if getattr(self._notification_state, "active", False):
            raise RuntimeError("检测到事件流 append 重入")

        try:
            serialized = json.dumps(payload, ensure_ascii=False)
            normalized_payload = json.loads(serialized)
        except (TypeError, ValueError) as exc:
            raise ValueError("事件 payload 必须是可 JSON 序列化的 dict") from exc
        schema_version = self._registry.validate(event_type, normalized_payload)

        with self._lock:
            event = DomainEvent(
                event_id=uuid.uuid4().hex,
                stream_id=self._stream_id,
                seq=len(self._events),
                event_type=event_type,
                timestamp=time.time(),
                schema_version=schema_version,
                payload=normalized_payload,
            )
            observers = tuple(self._observers)
            self._events.append(event)

        self._notification_state.active = True
        try:
            for observer in observers:
                try:
                    observer(event)
                except Exception:
                    logger.exception("事件 observer 通知失败，已保留已提交事件")
        finally:
            self._notification_state.active = False
        return event

    def subscribe(self, observer: Callable[[DomainEvent], None]) -> Callable[[], None]:
        """订阅事件并返回取消订阅函数。

        参数：
            observer: 接收已提交事件的回调。

        返回值：
            调用后取消本次订阅的函数。
        """
        with self._lock:
            self._observers.append(observer)

        def unsubscribe() -> None:
            with self._lock:
                if observer in self._observers:
                    self._observers.remove(observer)

        return unsubscribe

    def get_events(self, from_seq: int = 0) -> list[DomainEvent]:
        """返回从指定序号开始的事件快照。"""
        with self._lock:
            if from_seq < 0 or from_seq >= len(self._events):
                return []
            return list(self._events[from_seq:])

    def get_event(self, seq: int) -> DomainEvent | None:
        """按序号返回事件，不存在时返回 None。"""
        with self._lock:
            if 0 <= seq < len(self._events):
                return self._events[seq]
            return None
