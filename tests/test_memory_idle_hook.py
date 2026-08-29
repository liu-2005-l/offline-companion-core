from __future__ import annotations

import sqlite3
import time

from offline_companion.core.memory_lifecycle.decay import compute_decay_score, should_gc
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import SemanticEvent
from offline_companion.core.memory_lifecycle.idle_hook import MemoryIdleHook


class FakeExtractor:
    def __init__(self, result_count: int = 1, extraction_interval: int = 10) -> None:
        self.calls = []
        self.marked_turns: list[int] = []
        self._result_count = result_count
        self._extraction_interval = extraction_interval

    def extract(self, messages, session_id, turn_range):
        self.calls.append((messages, session_id, turn_range))
        return [object() for _index in range(self._result_count)]

    def should_extract(self, turn_count: int) -> bool:
        return turn_count > 0 and turn_count % self._extraction_interval == 0

    def mark_extracted(self, turn_count: int) -> None:
        self.marked_turns.append(turn_count)


class FakeSessionRepo:
    def __init__(self, pending=("s1", [{"role": "user", "content": "残余消息"}], (11, 12))) -> None:
        self.pending = pending

    def get_pending_extraction(self):
        return self.pending


def event(event_id: str, *, created_at: float, importance: float = 1.0, recall_count: int = 0) -> SemanticEvent:
    return SemanticEvent(
        event_id=event_id,
        event_type="fact",
        subject="user",
        content=event_id,
        created_at=created_at,
        importance=importance,
        recall_count=recall_count,
    )


def test_idle_hook_extracts_residual_messages_and_runs_gc() -> None:
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("stale", created_at=time.time() - 86400 * 1000))
    extractor = FakeExtractor()
    hook = MemoryIdleHook(extractor, repo, FakeSessionRepo())

    actions = hook.on_idle(300)

    assert extractor.calls[0][1:] == ("s1", (11, 12))
    assert extractor.marked_turns == [12]
    assert "extracted 1 events from residual turns" in actions
    assert "marked 1 events as dormant" in actions
    assert repo.get("stale").status == "dormant"


def test_idle_hook_extracts_residual_turn_ranges_before_interval_boundary() -> None:
    """摘要：空闲补提取只处理未到正常周期边界的残余轮次。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    extractor = FakeExtractor()
    hook = MemoryIdleHook(
        extractor,
        repo,
        FakeSessionRepo(("s1", [{"role": "user", "content": "残余"}], (11, 17))),
    )

    assert hook.on_idle(300) == ["extracted 1 events from residual turns"]
    assert extractor.calls[0][2] == (11, 17)
    assert extractor.marked_turns == [17]


def test_idle_hook_does_not_residual_extract_on_normal_interval_boundary() -> None:
    """摘要：当前轮次已到正常提取边界时，idle 不抢跑补提取。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    extractor = FakeExtractor()
    hook = MemoryIdleHook(
        extractor,
        repo,
        FakeSessionRepo(("s1", [{"role": "user", "content": "边界"}], (11, 20))),
    )

    assert hook.on_idle(300) == []
    assert extractor.calls == []
    assert extractor.marked_turns == []


def test_idle_hook_extracts_initial_residual_turns() -> None:
    """摘要：从未提取过时，idle 可补提取 turn 1 到当前残余轮次。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    extractor = FakeExtractor()
    hook = MemoryIdleHook(
        extractor,
        repo,
        FakeSessionRepo(("s1", [{"role": "user", "content": "初始残余"}], (1, 7))),
    )

    hook.on_idle(300)

    assert extractor.calls[0][2] == (1, 7)
    assert extractor.marked_turns == [7]


def test_idle_hook_skips_empty_or_invalid_pending_turn_range() -> None:
    """摘要：当前轮次为 0 或窗口非法时不触发补提取。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    extractor = FakeExtractor()
    zero_hook = MemoryIdleHook(extractor, repo, FakeSessionRepo(("s1", [], (1, 0))))
    reversed_hook = MemoryIdleHook(extractor, repo, FakeSessionRepo(("s1", [], (8, 7))))

    assert zero_hook.on_idle(300) == []
    assert reversed_hook.on_idle(300) == []
    assert extractor.calls == []


def test_idle_hook_below_threshold_does_nothing() -> None:
    extractor = FakeExtractor()
    repo = EventRepository(sqlite3.connect(":memory:"))
    hook = MemoryIdleHook(extractor, repo, FakeSessionRepo())

    assert hook.on_idle(299) == []
    assert extractor.calls == []


def test_idle_hook_at_and_above_threshold_runs() -> None:
    """摘要：idle_duration 达到或超过阈值时执行维护。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    at_threshold = FakeExtractor()
    above_threshold = FakeExtractor()

    assert MemoryIdleHook(at_threshold, repo, FakeSessionRepo(), minimum_idle_seconds=300).on_idle(300)
    assert MemoryIdleHook(above_threshold, repo, FakeSessionRepo(), minimum_idle_seconds=300).on_idle(600)
    assert at_threshold.calls
    assert above_threshold.calls


def test_decay_preserves_recalled_events() -> None:
    old = event("old", created_at=time.time() - 86400 * 1000, recall_count=1)

    assert compute_decay_score(old) > 0
    assert not should_gc(old)


def test_idle_hook_gc_marks_only_unrecalled_low_decay_active_events() -> None:
    """摘要：GC 只休眠低衰减且未召回的 active 事件。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    now = time.time()
    repo.store(event("stale", created_at=now - 86400 * 1000, recall_count=0))
    repo.store(event("recalled", created_at=now - 86400 * 1000, recall_count=1))
    repo.store(event("fresh", created_at=now, importance=5.0, recall_count=0))
    repo.store(
        SemanticEvent(
            event_id="already-dormant",
            event_type="fact",
            subject="user",
            content="already-dormant",
            created_at=now - 86400 * 1000,
            importance=1.0,
            status="dormant",
        )
    )
    hook = MemoryIdleHook(FakeExtractor(result_count=0), repo, FakeSessionRepo(None))

    actions = hook.on_idle(300)

    assert actions == ["marked 1 events as dormant"]
    assert repo.get("stale").status == "dormant"
    assert repo.get("recalled").status == "active"
    assert repo.get("fresh").status == "active"
    assert repo.get("already-dormant").status == "dormant"


def test_idle_hook_gc_reports_zero_when_no_candidates() -> None:
    """摘要：没有 GC 候选时不输出虚假 action。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("fresh", created_at=time.time(), importance=5.0))
    hook = MemoryIdleHook(FakeExtractor(result_count=0), repo, FakeSessionRepo(None))

    assert hook.on_idle(300) == []


def test_idle_hook_gc_marks_multiple_candidates() -> None:
    """摘要：多条低衰减候选会全部标记 dormant，并报告数量。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    now = time.time()
    for index in range(10):
        repo.store(event(f"stale-{index}", created_at=now - 86400 * 1000))
    hook = MemoryIdleHook(FakeExtractor(result_count=0), repo, FakeSessionRepo(None))

    assert hook.on_idle(300) == ["marked 10 events as dormant"]
    assert all(repo.get(f"stale-{index}").status == "dormant" for index in range(10))


def test_idle_hook_combined_actions_and_db_status_are_auditable() -> None:
    """摘要：残余补提取与 GC 同轮发生时返回两条动作并落库 dormant 状态。"""
    repo = EventRepository(sqlite3.connect(":memory:"))
    repo.store(event("stale", created_at=time.time() - 86400 * 1000))
    extractor = FakeExtractor(result_count=2)
    hook = MemoryIdleHook(extractor, repo, FakeSessionRepo())

    actions = hook.on_idle(300)

    assert actions == ["extracted 2 events from residual turns", "marked 1 events as dormant"]
    assert repo.get("stale").status == "dormant"
