"""AttentionGuard：对提醒候选执行场景静默、频率硬锁和降级。"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from enum import Enum

from offline_companion.shared.types import ReminderCandidate


class QuietLevel(str, Enum):
    """摘要：提醒经过注意力闸门后的静默级别。"""

    ALLOW = "allow"
    SILENT = "silent"
    SUPPRESS = "suppress"


@dataclass
class AttentionContext:
    """摘要：由 A1 层填充的注意力感知上下文。"""

    is_focus_mode: bool = False
    is_night_time: bool = False
    is_idle: bool = False
    last_idle_at: float | None = None
    last_global_reminder_at: float | None = None
    urgent_only_mode: bool = False


@dataclass
class AttentionGuardConfig:
    """摘要：AttentionGuard 的可调决策参数。"""

    night_start_hour: int = 22
    night_end_hour: int = 8
    global_cooldown_minutes: float = 30.0
    daily_global_cap: int = 5
    silent_urgency_threshold: float = 0.3
    suppress_urgency_threshold: float = 0.15
    now: float | None = None


class AttentionGuard:
    """摘要：纯决策过滤提醒候选，不负责实际展示。"""

    def __init__(self, config: AttentionGuardConfig | None = None) -> None:
        self._cfg = config or AttentionGuardConfig()
        self._daily_reminder_count = 0
        self._day_start: float | None = None

    def filter(
        self,
        candidates: list[ReminderCandidate],
        context: AttentionContext,
        now: float | None = None,
    ) -> list[tuple[ReminderCandidate, QuietLevel]]:
        """摘要：返回允许展示或需静默记录的候选及其级别。"""
        timestamp = now if now is not None else (self._cfg.now if self._cfg.now is not None else time.time())
        self._maybe_reset_daily_count(timestamp)
        is_night = context.is_night_time or self._is_night_time(timestamp)
        focus_block = context.is_focus_mode or (is_night and not context.is_idle)
        in_global_cooldown = (
            context.last_global_reminder_at is not None
            and (timestamp - context.last_global_reminder_at) / 60.0 < self._cfg.global_cooldown_minutes
        )
        global_cap_reached = self._daily_reminder_count >= self._cfg.daily_global_cap

        results: list[tuple[ReminderCandidate, QuietLevel]] = []
        for candidate in candidates:
            level = self._evaluate_single(
                candidate,
                context,
                focus_block=focus_block,
                in_global_cooldown=in_global_cooldown,
                global_cap_reached=global_cap_reached,
            )
            if level != QuietLevel.SUPPRESS:
                results.append((candidate, level))
        return results

    def record_shown(self, now: float | None = None) -> None:
        """摘要：在调用方实际展示提醒后更新全局每日计数。"""
        timestamp = now if now is not None else (self._cfg.now if self._cfg.now is not None else time.time())
        self._maybe_reset_daily_count(timestamp)
        self._daily_reminder_count += 1

    def _evaluate_single(
        self,
        candidate: ReminderCandidate,
        context: AttentionContext,
        *,
        focus_block: bool,
        in_global_cooldown: bool,
        global_cap_reached: bool,
    ) -> QuietLevel:
        """摘要：按硬抑制、场景静默和频率锁顺序判断单个候选。"""
        if candidate.urgency < self._cfg.suppress_urgency_threshold:
            return QuietLevel.SUPPRESS
        if focus_block and candidate.priority != "urgent":
            if candidate.urgency < self._cfg.silent_urgency_threshold:
                return QuietLevel.SUPPRESS
            return QuietLevel.SILENT
        if context.urgent_only_mode and candidate.priority != "urgent":
            return QuietLevel.SUPPRESS
        if (in_global_cooldown or global_cap_reached) and candidate.priority != "urgent":
            return QuietLevel.SILENT
        if candidate.urgency < self._cfg.silent_urgency_threshold:
            return QuietLevel.SILENT
        return QuietLevel.ALLOW

    def _is_night_time(self, now: float) -> bool:
        """摘要：按本地时间判断当前是否处于配置的夜间时段。"""
        hour = datetime.datetime.fromtimestamp(now, tz=datetime.UTC).astimezone().hour
        if self._cfg.night_start_hour > self._cfg.night_end_hour:
            return hour >= self._cfg.night_start_hour or hour < self._cfg.night_end_hour
        return self._cfg.night_start_hour <= hour < self._cfg.night_end_hour

    def _maybe_reset_daily_count(self, now: float) -> None:
        """摘要：首次使用或本地日期变化时重置全局每日计数。"""
        today = datetime.datetime.fromtimestamp(now, tz=datetime.UTC).astimezone().date()
        previous_day = (
            None
            if self._day_start is None
            else datetime.datetime.fromtimestamp(self._day_start, tz=datetime.UTC).astimezone().date()
        )
        if previous_day != today:
            self._day_start = now
            self._daily_reminder_count = 0
