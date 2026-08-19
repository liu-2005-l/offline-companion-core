"""IdleThink 触发的语义事件补提取与衰减维护。"""

from __future__ import annotations

import time
from typing import Any

from .decay import should_gc
from .event_extractor import EventExtractor
from .event_repository import EventRepository


class MemoryIdleHook:
    """摘要：在用户空闲时补提取残余消息并执行事件 GC。"""

    def __init__(
        self,
        extractor: EventExtractor,
        repo: EventRepository,
        session_repo: Any,
        minimum_idle_seconds: float = 300.0,
    ) -> None:
        self._extractor = extractor
        self._repo = repo
        self._session_repo = session_repo
        self._minimum_idle_seconds = minimum_idle_seconds

    def on_idle(self, idle_duration: float = 300.0) -> list[str]:
        """摘要：执行一次空闲维护并返回可审计的动作摘要。"""
        if idle_duration < self._minimum_idle_seconds:
            return []
        actions: list[str] = []
        pending = self._get_pending_extraction()
        if pending is not None:
            session_id, messages, turn_range = pending
            events = self._extractor.extract(messages, session_id, turn_range)
            if events:
                actions.append(f"extracted {len(events)} events from residual turns")
        gc_count = 0
        now = time.time()
        for event in self._repo.get_active(limit=5000):
            if should_gc(event, now):
                self._repo.mark_dormant(event.event_id)
                gc_count += 1
        if gc_count:
            actions.append(f"marked {gc_count} events as dormant")
        return actions

    def _get_pending_extraction(self) -> tuple[str, list[dict[str, Any]], tuple[int, int]] | None:
        """摘要：读取会话仓库提供的未提取消息窗口。"""
        getter = getattr(self._session_repo, "get_pending_extraction", None)
        if getter is None:
            return None
        pending = getter()
        if not isinstance(pending, tuple) or len(pending) != 3:
            return None
        session_id, messages, turn_range = pending
        if not isinstance(session_id, str) or not isinstance(messages, list):
            return None
        if not isinstance(turn_range, tuple) or len(turn_range) != 2:
            return None
        return session_id, messages, (int(turn_range[0]), int(turn_range[1]))
