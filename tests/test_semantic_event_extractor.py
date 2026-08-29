from __future__ import annotations

import logging
import sqlite3

from offline_companion.core.memory_lifecycle.event_extractor import (
    HASH_BOW_DUPLICATE_THRESHOLD,
    EventExtractor,
)
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import CONTENT_EMBEDDING_DIMENSIONS
from offline_companion.shared.deterministic_embedding import embed_text


class FakeLlm:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, temperature: float) -> str:
        self.prompts.append(prompt)
        assert temperature == 0.3
        return self.response


class SequenceLlm:
    """摘要：按调用顺序返回多个结构化提取响应。"""

    def __init__(self, responses: list[str]) -> None:
        """摘要：保存待返回的响应序列。"""
        self.responses = responses

    def generate(self, prompt: str, *, temperature: float) -> str:
        """摘要：返回下一条响应，并校验提取温度。"""
        assert temperature == 0.3
        return self.responses.pop(0)


def make_extractor(response: str) -> tuple[EventExtractor, EventRepository, FakeLlm]:
    llm = FakeLlm(response)
    repo = EventRepository(sqlite3.connect(":memory:"))
    extractor = EventExtractor(
        repo,
        llm,
        lambda content: [1.0] + [0.0] * (CONTENT_EMBEDDING_DIMENSIONS - 1),
    )
    return extractor, repo, llm


def make_hash_bow_extractor(responses: list[str]) -> tuple[EventExtractor, EventRepository]:
    """摘要：构造使用真实 deterministic hash-bow 的提取器。"""
    llm = SequenceLlm(responses)
    repo = EventRepository(sqlite3.connect(":memory:"))
    extractor = EventExtractor(
        repo,
        llm,
        lambda content: embed_text(content, dimensions=CONTENT_EMBEDDING_DIMENSIONS),
    )
    return extractor, repo


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


def test_extract_skips_literal_near_duplicate_with_hash_bow_threshold() -> None:
    """摘要：hash-bow 字面近似重复达到 0.50 阈值时不重复存储。"""
    assert HASH_BOW_DUPLICATE_THRESHOLD == 0.50
    extractor, repo = make_hash_bow_extractor(
        [
            '[{"event_type":"fact","subject":"user","content":"用户对花生过敏"}]',
            '[{"event_type":"fact","subject":"user","content":"用户对花生严重过敏"}]',
        ]
    )

    first = extractor.extract([{"role": "user", "content": "花生"}], "s1", (1, 1))
    second = extractor.extract([{"role": "user", "content": "严重花生过敏"}], "s1", (2, 2))

    assert len(first) == 1
    assert second == []
    assert len(repo.get_active()) == 1


def test_extract_supersedes_lower_importance_literal_duplicate() -> None:
    """摘要：字面近似重复中，新事件重要性更高时替代旧事件。"""
    extractor, repo = make_hash_bow_extractor(
        [
            '[{"event_type":"fact","subject":"user","content":"用户是 C++ 工程师","importance":2}]',
            '[{"event_type":"fact","subject":"user","content":"用户是资深 C++ 工程师","importance":4}]',
        ]
    )

    first = extractor.extract([{"role": "user", "content": "C++"}], "s1", (1, 10))
    second = extractor.extract([{"role": "user", "content": "资深 C++"}], "s1", (11, 20))

    assert len(first) == 1
    assert len(second) == 1
    assert repo.get(first[0].event_id).status == "superseded"
    assert repo.get(first[0].event_id).superseded_by == second[0].event_id
    assert [event.event_id for event in repo.get_active()] == [second[0].event_id]


def test_extract_keeps_paraphrase_below_hash_bow_threshold() -> None:
    """摘要：hash-bow 无法判别的同义改写按降级口径双份存储。"""
    extractor, repo = make_hash_bow_extractor(
        [
            '[{"event_type":"preference","subject":"user","content":"用户重视用户视角验收"}]',
            '[{"event_type":"preference","subject":"user","content":"用户认为通过测试不等于产品正确"}]',
        ]
    )

    first = extractor.extract([{"role": "user", "content": "用户视角"}], "s1", (1, 1))
    second = extractor.extract([{"role": "user", "content": "测试不等于产品正确"}], "s1", (2, 2))

    assert len(first) == 1
    assert len(second) == 1
    assert len(repo.get_active()) == 2


def test_extract_keeps_semantic_paraphrase_when_literal_overlap_is_low() -> None:
    """摘要：真 semantic 向量不把写端去重静默漂移成语义去重。"""

    class SemanticSameVector:
        embedding_space = "semantic_onnx_768"

        def __call__(self, _content: str) -> list[float]:
            return [1.0] + [0.0] * (CONTENT_EMBEDDING_DIMENSIONS - 1)

    llm = SequenceLlm(
        [
            '[{"event_type":"fact","subject":"user","content":"relocate shanghai next spring"}]',
            '[{"event_type":"fact","subject":"user","content":"move magiccity after winter"}]',
        ]
    )
    repo = EventRepository(sqlite3.connect(":memory:"))
    extractor = EventExtractor(repo, llm, SemanticSameVector())

    first = extractor.extract([{"role": "user", "content": "relocate"}], "s1", (1, 1))
    second = extractor.extract([{"role": "user", "content": "move"}], "s1", (2, 2))

    assert len(first) == 1
    assert len(second) == 1
    assert len(repo.get_active()) == 2


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


def test_extract_stores_event_without_embedding_when_embedding_fails() -> None:
    """摘要：embedding 函数失败时事件仍可落库，向量字段降级为空。"""
    llm = FakeLlm('[{"event_type":"fact","subject":"user","content":"用户喜欢本地优先","importance":3}]')
    repo = EventRepository(sqlite3.connect(":memory:"))

    def fail_embed(_content: str) -> list[float]:
        raise RuntimeError("embedding offline")

    extractor = EventExtractor(repo, llm, fail_embed)

    events = extractor.extract([{"role": "user", "content": "本地优先"}], "s1", (1, 10))

    assert len(events) == 1
    stored = repo.get(events[0].event_id)
    assert stored is not None
    assert stored.content_embedding is None
    assert stored.content_embedding_space == "none"
