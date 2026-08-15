"""从领域事件投影出开发模式可读视图。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from .types import DomainEvent

ProjectionHandler = Callable[[DomainEvent, dict[str, Any]], None]


class Projection:
    """按事件类型注册处理器并生成独立的投影状态。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[ProjectionHandler]] = defaultdict(list)

    def on(self, event_type: str) -> Callable[[ProjectionHandler], ProjectionHandler]:
        """注册指定事件类型的投影处理器。"""

        def decorator(handler: ProjectionHandler) -> ProjectionHandler:
            self._handlers[event_type].append(handler)
            return handler

        return decorator

    def project(self, events: Iterable[DomainEvent]) -> dict[str, Any]:
        """按 seq 顺序将事件投影为时间线与汇总。"""
        state: dict[str, Any] = {"timeline": [], "summary": {}}
        for event in sorted(events, key=lambda item: item.seq):
            for handler in self._handlers.get(event.event_type, ()):
                handler(event, state)
        state["summary"]["event_count"] = len(state["timeline"])
        return state


def build_trajectory_projection() -> Projection:
    """创建开发模式 Trajectory 时间线投影。"""
    projection = Projection()

    def add_timeline(event: DomainEvent, state: dict[str, Any], kind: str) -> None:
        state["timeline"].append(
            {
                "seq": event.seq,
                "type": kind,
                "timestamp": event.timestamp,
                "trace_id": event.payload.get("trace_id"),
                "payload": event.payload,
            }
        )

    @projection.on("session/turn_start")
    def on_turn_start(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "turn_start")

    @projection.on("session/turn_end")
    def on_turn_end(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "turn_end")

    @projection.on("session/message")
    def on_message(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, f"message_{event.payload.get('role', 'unknown')}")

    @projection.on("plan/step_started")
    def on_step_started(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "step_started")
        state["summary"]["current_step"] = event.payload.get("step_title") or event.payload.get("step_id")

    @projection.on("plan/step_completed")
    def on_step_completed(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "step_completed")

    @projection.on("plan/step_failed")
    def on_step_failed(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "step_failed")
        state["summary"]["last_error"] = event.payload.get("error")

    @projection.on("plan/status_changed")
    def on_plan_status(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "plan_status_changed")
        state["summary"]["plan_status"] = event.payload.get("status")

    @projection.on("consent/asked")
    def on_consent_asked(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "consent_asked")

    @projection.on("consent/decided")
    def on_consent_decided(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "consent_decided")

    @projection.on("model/switched")
    def on_model_switched(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "model_switched")
        state["summary"]["model"] = event.payload.get("model")

    @projection.on("model/degraded")
    def on_model_degraded(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "model_degraded")

    @projection.on("model/unavailable")
    def on_model_unavailable(event: DomainEvent, state: dict[str, Any]) -> None:
        add_timeline(event, state, "model_unavailable")

    return projection


TRAJECTORY_PROJECTION = build_trajectory_projection()
