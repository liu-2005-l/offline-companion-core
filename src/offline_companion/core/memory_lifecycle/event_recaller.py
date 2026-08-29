"""语义事件的多路检索、事件链扩展和叙事排序。"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from .event_extractor import HASH_BOW_DUPLICATE_THRESHOLD
from .event_repository import EventRepository
from .event_types import SemanticEvent
from .semantic_embedding_provider import embedding_space_of

RRF_K = 60
HASH_BOW_RECALL_THRESHOLD = HASH_BOW_DUPLICATE_THRESHOLD
logger = logging.getLogger(__name__)


def format_event_narrative(events: list[SemanticEvent]) -> str:
    """摘要：把事件按时间顺序格式化为模型可读的叙事上下文。"""
    if not events:
        return ""
    lines = ["【相关语义事件】仅作为历史参考，不要把未列出的内容当作事实。"]
    for event in events:
        emotion = ""
        if abs(event.emotional_valence) > 0.3 or event.emotional_arousal > 0.3:
            emotion = (
                f"（{_valence_label(event.emotional_valence)}, "
                f"{_arousal_label(event.emotional_arousal)}；"
                f"情感效价 {event.emotional_valence:.2f}，唤醒度 {event.emotional_arousal:.2f}）"
            )
        marker = event.temporal_marker or time.strftime("%Y-%m-%d", time.localtime(event.created_at))
        lines.append(f"- [{marker}] [{event.event_type}] {event.content}{emotion}")
    return "\n".join(lines)


class EventRecaller:
    """摘要：执行三阶段语义事件召回。

    参数：
        repo: 语义事件仓库。
        bm25: 可选的外部 BM25 检索函数，签名为 ``(query) -> ids``。
        hash_bow: 可选的外部 hash-bow 检索函数，签名为 ``(query) -> ids``。
        embed_func: 将查询转换为向量的函数。
        llm_backend: 可选的查询扩展 LLM。
    """

    def __init__(
        self,
        repo: EventRepository,
        bm25: Callable[[str], list[Any]] | None = None,
        hash_bow: Callable[[str], list[Any]] | None = None,
        embed_func: Callable[[str], list[float]] | None = None,
        llm_backend: Any | None = None,
    ) -> None:
        self._repo = repo
        self._bm25 = bm25
        self._hash_bow = hash_bow
        self._embed = embed_func
        self._llm = llm_backend

    def recall(
        self,
        query: str,
        emotional_context: dict[str, float] | None = None,
        top_k: int = 5,
    ) -> list[SemanticEvent]:
        """摘要：召回相关事件并按时间顺序组织为叙事链。"""
        query = query.strip()
        if not query or top_k <= 0:
            return []
        try:
            candidates = self._repo.get_active(limit=max(top_k * 20, 100))
        except sqlite3.Error:
            return []
        by_id = {event.event_id: event for event in candidates}
        queries = self._expand_query(query)
        ranked_paths: dict[str, list[str]] = {"vector": [], "bm25": [], "hash_bow": []}
        for expanded in queries:
            ranked_paths["vector"].extend(self._vector_ids(expanded, by_id))
            ranked_paths["bm25"].extend(self._path_ids(self._bm25, expanded, by_id))
            ranked_paths["hash_bow"].extend(self._path_ids(self._hash_bow, expanded, by_id))
        if not ranked_paths["bm25"]:
            ranked_paths["bm25"] = self._lexical_ids(query, candidates)
        if not ranked_paths["hash_bow"]:
            ranked_paths["hash_bow"] = self._overlap_ids(query, candidates)

        fused = self._rrf_fuse(ranked_paths)
        sources_by_id = self._source_paths(ranked_paths)
        ranked: list[tuple[float, SemanticEvent]] = []
        for event_id, rrf_score in fused.items():
            event = by_id.get(event_id)
            if event is None:
                continue
            score = rrf_score * self._decay_score(event)
            if emotional_context is not None:
                score *= 1.0 + 0.30 * self._emotional_similarity(
                    emotional_context, event.emotional_valence, event.emotional_arousal
                )
            ranked.append((score, event))
        ranked.sort(key=lambda item: item[0], reverse=True)
        fused_top = [
            {
                "id": event.event_id,
                "rrf_score": round(fused.get(event.event_id, 0.0), 6),
                "sources": sources_by_id.get(event.event_id, ()),
            }
            for _score, event in ranked[:top_k]
        ]
        selected = [event for _score, event in ranked[:top_k]]
        selected = self._expand_event_chain(selected, by_id, top_k)
        selected.sort(key=lambda event: (event.created_at, event.event_id))
        final_ids = [event.event_id for event in selected]
        logger.info(
            "semantic event recall paths query=%r vector=%d bm25=%d hash_bow=%d "
            "top_k=%d fused_top=%s expansion_count=%d final_ids=%s",
            self._summarize_query(query),
            len(ranked_paths["vector"]),
            len(ranked_paths["bm25"]),
            len(ranked_paths["hash_bow"]),
            top_k,
            fused_top,
            max(0, len(final_ids) - len(fused_top)),
            final_ids,
        )
        for event in selected:
            self._repo.update_recall_stats(event.event_id)
        return selected

    def _vector_ids(self, query: str, by_id: dict[str, SemanticEvent]) -> list[str]:
        if self._embed is None:
            return []
        try:
            query_embedding = self._embed(query)
            query_space = embedding_space_of(self._embed)
            results = self._repo.vector_search(
                query_embedding,
                top_k=max(len(by_id), 1),
                embedding_space=query_space,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return []
        return [
            event.event_id
            for event, distance in results
            if event.event_id in by_id and 1.0 - distance >= HASH_BOW_RECALL_THRESHOLD
        ]

    @staticmethod
    def _path_ids(
        path: Callable[[str], list[Any]] | None,
        query: str,
        by_id: dict[str, SemanticEvent],
    ) -> list[str]:
        if path is None:
            return []
        try:
            values = path(query)
        except (OSError, RuntimeError, TypeError, ValueError):
            return []
        ids: list[str] = []
        for value in values:
            event_id = value.event_id if isinstance(value, SemanticEvent) else str(value)
            if event_id in by_id:
                ids.append(event_id)
        return ids

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        words = re.findall(r"[a-z0-9]{2,}", text.lower())
        cjk = re.findall(r"[\u4e00-\u9fff]", text)
        words.extend(cjk)
        words.extend(cjk[index] + cjk[index + 1] for index in range(len(cjk) - 1))
        return set(words)

    def _lexical_ids(self, query: str, events: list[SemanticEvent]) -> list[str]:
        query_tokens = self._tokenize(query)
        ranked = [
            (len(query_tokens & self._tokenize(event.content)), event.event_id)
            for event in events
        ]
        return [event_id for score, event_id in sorted(ranked, key=lambda item: (-item[0], item[1])) if score]

    def _overlap_ids(self, query: str, events: list[SemanticEvent]) -> list[str]:
        return self._lexical_ids(query, events)

    @staticmethod
    def _rrf_fuse(candidates: dict[str, list[str]], k: int = RRF_K) -> dict[str, float]:
        """摘要：以 Reciprocal Rank Fusion 合并不同检索路径。"""
        scores: dict[str, float] = {}
        for ranked in candidates.values():
            seen: set[str] = set()
            for rank, event_id in enumerate(ranked):
                if event_id in seen:
                    continue
                seen.add(event_id)
                scores[event_id] = scores.get(event_id, 0.0) + 1.0 / (k + rank)
        return scores

    @staticmethod
    def _source_paths(candidates: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
        """摘要：记录每个事件 ID 来自哪些检索路径，供 RRF anchor 解释来源。"""
        paths: dict[str, list[str]] = {}
        for path_name, ranked in candidates.items():
            for event_id in ranked:
                path_names = paths.setdefault(event_id, [])
                if path_name not in path_names:
                    path_names.append(path_name)
        return {event_id: tuple(path_names) for event_id, path_names in paths.items()}

    @staticmethod
    def _summarize_query(query: str, limit: int = 48) -> str:
        """摘要：压缩查询文本用于日志 anchor，避免长输入刷屏。"""
        compact = re.sub(r"\s+", " ", query).strip()
        if len(compact) <= limit:
            return compact
        return f"{compact[: limit - 1]}…"

    def _expand_query(self, query: str) -> list[str]:
        """摘要：用 LLM 生成最多三个语义变体，失败时保留原查询。"""
        if self._llm is None:
            return [query]
        try:
            response = self._llm.generate(
                f"将以下记忆查询改写为三个语义等价表达，每行一个，不要编号：\n{query}",
                temperature=0.5,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return [query]
        if not isinstance(response, str):
            return [query]
        variants = [line.strip(" -*\t") for line in response.splitlines() if line.strip()]
        return [query, *[variant for variant in variants if variant and variant != query][:3]]

    @staticmethod
    def _emotional_similarity(
        context: dict[str, float], event_valence: float, event_arousal: float
    ) -> float:
        """摘要：计算 valence/arousal 二维情感相似度，结果范围为 0 到 1。"""
        context_valence = float(context.get("valence", 0.0))
        context_arousal = float(context.get("arousal", 0.5))
        valence_distance = abs((event_valence + 1.0) / 2.0 - (context_valence + 1.0) / 2.0)
        arousal_distance = abs(event_arousal - context_arousal)
        distance = math.sqrt(valence_distance**2 + arousal_distance**2)
        return max(0.0, 1.0 - distance / math.sqrt(2.0))

    @staticmethod
    def _decay_score(event: SemanticEvent, now: float | None = None, half_life_days: float = 30.0) -> float:
        """摘要：计算时间衰减与召回反馈结合后的事件分数。"""
        current = time.time() if now is None else now
        age_days = max(0.0, current - event.created_at) / 86400.0
        decay = math.exp(-age_days / half_life_days) if half_life_days > 0 else 1.0
        recall_boost = min(1.0 + event.recall_count * 0.1, 2.0)
        return event.importance * decay * recall_boost

    def _expand_event_chain(
        self,
        selected: list[SemanticEvent],
        by_id: dict[str, SemanticEvent],
        top_k: int,
    ) -> list[SemanticEvent]:
        """摘要：扩展一跳关联事件，仅纳入重要性至少为 3 的事件。"""
        result = list(selected)
        seen = {event.event_id for event in result}
        for event in selected:
            for related_id in event.related_events:
                related = by_id.get(related_id) or self._repo.get(related_id)
                if related is None or related.status != "active" or related.importance < 3.0:
                    continue
                if related.event_id not in seen:
                    result.append(related)
                    seen.add(related.event_id)
        del top_k
        return result


def _valence_label(value: float) -> str:
    """摘要：把情感效价映射为叙事标签。"""
    if value > 0.3:
        return "积极"
    if value < -0.3:
        return "消极"
    return "中性"


def _arousal_label(value: float) -> str:
    """摘要：把唤醒度映射为叙事标签。"""
    if value > 0.5:
        return "激动"
    return "平静"
