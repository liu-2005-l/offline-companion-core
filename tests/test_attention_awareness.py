from __future__ import annotations

from offline_companion.core.attention_awareness import (
    AttentionContext,
    AttentionGuard,
    AttentionGuardConfig,
    QuietLevel,
)
from offline_companion.shared.types import ReminderCandidate

NOW = 2_000_000_000.0


def _candidate(*, urgency: float = 0.6, priority: str = "normal") -> ReminderCandidate:
    return ReminderCandidate("1", "完成发布", urgency, "常规提醒", priority, None, 0.0, 1.0)


def _guard(**changes: object) -> AttentionGuard:
    return AttentionGuard(AttentionGuardConfig(now=NOW, night_start_hour=0, night_end_hour=0, **changes))


def test_allows_normal_candidate() -> None:
    candidate = _candidate()
    assert _guard().filter([candidate], AttentionContext()) == [(candidate, QuietLevel.ALLOW)]


def test_focus_or_night_silences_non_urgent_but_allows_urgent() -> None:
    normal = _candidate()
    urgent = _candidate(priority="urgent")
    context = AttentionContext(is_focus_mode=True)
    assert _guard().filter([normal, urgent], context) == [
        (normal, QuietLevel.SILENT),
        (urgent, QuietLevel.ALLOW),
    ]
    assert _guard().filter([normal], AttentionContext(is_night_time=True, is_idle=False)) == [
        (normal, QuietLevel.SILENT)
    ]


def test_urgent_only_suppresses_non_urgent() -> None:
    assert _guard().filter([_candidate()], AttentionContext(urgent_only_mode=True)) == []


def test_global_cooldown_and_cap_silence_non_urgent() -> None:
    candidate = _candidate()
    cooldown = AttentionContext(last_global_reminder_at=NOW - 60.0)
    assert _guard().filter([candidate], cooldown) == [(candidate, QuietLevel.SILENT)]

    guard = _guard(daily_global_cap=1)
    guard.record_shown()
    assert guard.filter([candidate], AttentionContext()) == [(candidate, QuietLevel.SILENT)]


def test_urgency_thresholds_suppress_or_silence() -> None:
    guard = _guard()
    assert guard.filter([_candidate(urgency=0.1)], AttentionContext()) == []
    candidate = _candidate(urgency=0.2)
    assert guard.filter([candidate], AttentionContext()) == [(candidate, QuietLevel.SILENT)]


def test_daily_count_resets_across_local_date() -> None:
    guard = _guard(daily_global_cap=1)
    guard.record_shown(now=NOW)
    assert guard.filter([_candidate()], AttentionContext(), now=NOW) == [(_candidate(), QuietLevel.SILENT)]
    assert guard.filter([_candidate()], AttentionContext(), now=NOW + 86400.0) == [(_candidate(), QuietLevel.ALLOW)]
