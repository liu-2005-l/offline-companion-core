from __future__ import annotations

import logging
import sqlite3

from offline_companion.core.memory_lifecycle.event_extractor import EventExtractor
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import CONTENT_EMBEDDING_DIMENSIONS


class FakeLlm:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, temperature: float) -> str:
        self.prompts.append(prompt)
        assert temperature == 0.3
        return self.response


def make_extractor(response: str) -> tuple[EventExtractor, EventRepository, FakeLlm]:
    llm = FakeLlm(response)
    repo = EventRepository(sqlite3.connect(":memory:"))
    extractor = EventExtractor(
        repo,
        llm,
        lambda content: [1.0] + [0.0] * (CONTENT_EMBEDDING_DIMENSIONS - 1),
    )
    return extractor, repo, llm


def test_should_extract_only_on_interval() -> None:
    extractor, _repo, _llm = make_extractor("[]")

    assert not extractor.should_extract(9)
    assert extractor.should_extract(10)
    assert not extractor.should_extract(11)


def test_extract_parses_structured_events_and_persists_metadata() -> None:
    extractor, repo, llm = make_extractor(
        '```json\n[{"event_type":"decision","subject":"user",'
        '"content":"决定采用本地方案","emotional_valence":0.2,'
        '"emotional_arousal":0.4,"importance":4}]\n```'
    )

    events = extractor.extract(
        [{"role": "user", "content": "我们决定采用本地方案"}], "s1", (1, 1)
    )

    assert len(events) == 1
    assert repo.get(events[0].event_id).temporal_marker == "session:s1:turn:1-1"
    assert events[0].source_turns == [1]
    assert "本地方案" in llm.prompts[0]


def test_extract_logs_turn_range_anchor(caplog) -> None:
    """摘要：语义提取固定输出轮次范围 anchor，避免日志存在但不可诊断。"""
    extractor, _repo, _llm = make_extractor(
        '[{"event_type":"decision","subject":"user",'
        '"content":"决定采用本地方案","emotional_valence":0.2,'
        '"emotional_arousal":0.4,"importance":4}]'
    )

    with caplog.at_level(logging.INFO, logger="offline_companion.core.memory_lifecycle.event_extractor"):
        extractor.extract([{"role": "user", "content": "我们决定采用本地方案"}], "s1", (3, 4))

    assert "semantic extractor extracted 1 events from turns 3-4 candidates=1" in caplog.text


def test_extract_skips_duplicate_event_by_embedding_similarity() -> None:
    extractor, repo, _llm = make_extractor(
        '[{"event_type":"fact","subject":"user","content":"用户使用 Python"}]'
    )

    first = extractor.extract([{"role": "user", "content": "Python"}], "s1", (1, 1))
    second = extractor.extract([{"role": "user", "content": "Python"}], "s1", (2, 2))

    assert len(first) == 1
    assert second == []
    assert len(repo.get_active()) == 1


def test_extract_ignores_malformed_or_invalid_events() -> None:
    extractor, repo, _llm = make_extractor(
        '[{"event_type":"unknown","content":"bad"},'
        '{"event_type":"fact","content":""}]'
    )

    assert extractor.extract([{"role": "user", "content": "闲聊"}], "s1", (1, 1)) == []
    assert repo.get_active() == []


def test_extract_handles_invalid_llm_json() -> None:
    extractor, repo, _llm = make_extractor("not json")

    assert extractor.extract([{"role": "user", "content": "内容"}], "s1", (1, 1)) == []
    assert repo.get_active() == []
