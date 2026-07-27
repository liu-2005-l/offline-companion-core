"""摘要：知识库与记忆库的双源融合检索管线（P3-A）。"""

from __future__ import annotations

import hashlib
import re
import sqlite3

from offline_companion.core.memory_lifecycle.recall import recall
from offline_companion.shared.types import Citation, HybridSearchResult, RetrievalHit

from .search import KnowledgeSearchHit, search_knowledge, search_knowledge_semantic

_RRF_K = 60


def hybrid_retrieve(
    *,
    query: str,
    knowledge_conn: sqlite3.Connection,
    companion_conn: sqlite3.Connection,
    knowledge_limit: int = 5,
    memory_limit: int = 5,
    final_limit: int = 8,
    emotion: str | None = None,
) -> HybridSearchResult:
    """摘要：融合知识路与记忆路结果，输出去重后的引用结果。

    参数:
        query: 用户查询。
        knowledge_conn: `knowledge.db` 连接。
        companion_conn: `companion.db` 连接。
        knowledge_limit: 知识路召回上限。
        memory_limit: 记忆路召回上限。
        final_limit: 融合后输出上限。
        emotion: 当前用户情绪标签，仅作用于记忆路内部排序。

    返回值:
        包含统一命中、引用列表与展示文本的 `HybridSearchResult`。
    """
    knowledge_hits = search_knowledge(knowledge_conn, query, limit=knowledge_limit)
    semantic_hits = search_knowledge_semantic(knowledge_conn, query, limit=knowledge_limit)
    memory_hits = recall(companion_conn, query, limit=memory_limit, emotion=emotion)

    retrieval_lists = (
        _adapt_knowledge_hits(knowledge_hits, retriever="knowledge_lexical"),
        _adapt_knowledge_hits(semantic_hits, retriever="knowledge_semantic"),
        _adapt_memory_hits(memory_hits),
    )
    fused_hits = _rrf_fuse(retrieval_lists, limit=final_limit)
    citations = tuple(
        Citation(
            index=index,
            source_type=hit.source_type,
            source_id=hit.source_id,
            title=hit.title,
            snippet=hit.snippet,
            score=hit.score,
        )
        for index, hit in enumerate(fused_hits, start=1)
    )
    return HybridSearchResult(
        hits=tuple(fused_hits),
        citations=citations,
        display_text=_format_hybrid_display(citations),
    )


def _adapt_knowledge_hits(hits: list[KnowledgeSearchHit], *, retriever: str) -> list[RetrievalHit]:
    """摘要：将知识库命中适配为统一 `RetrievalHit`。"""
    out: list[RetrievalHit] = []
    for rank, hit in enumerate(hits, start=1):
        out.append(
            RetrievalHit(
                source_type="knowledge",
                source_id=f"chunk:{hit.chunk_id}",
                title=hit.title,
                snippet=hit.body.strip(),
                score=_knowledge_score(hit.score),
                rank=rank,
                metadata={
                    "doc_id": hit.doc_id,
                    "chunk_id": hit.chunk_id,
                    "source_uri": hit.source_uri,
                    "raw_score": hit.score,
                    "retriever": retriever,
                },
            )
        )
    return out


def _adapt_memory_hits(hits) -> list[RetrievalHit]:
    """摘要：将记忆召回命中适配为统一 `RetrievalHit`。"""
    out: list[RetrievalHit] = []
    for rank, hit in enumerate(hits, start=1):
        out.append(
            RetrievalHit(
                source_type="memory",
                source_id=f"memory:{hit.id}",
                title=None,
                snippet=hit.body.strip(),
                score=float(hit.combined_score),
                rank=rank,
                metadata={
                    "memory_id": hit.id,
                    "created_at": hit.created_at,
                    "decay_factor": hit.decay_factor,
                    "matched_on": dict(hit.matched_on),
                },
            )
        )
    return out


def _rrf_fuse(retrieval_lists: tuple[list[RetrievalHit], ...], *, limit: int) -> list[RetrievalHit]:
    """摘要：使用 RRF 融合多路排序结果，并做跨库去重。"""
    by_key: dict[str, RetrievalHit] = {}
    fused_scores: dict[str, float] = {}
    content_keys: dict[str, str] = {}

    for hits in retrieval_lists:
        for hit in hits:
            dedupe_key = _primary_dedupe_key(hit)
            content_key = _content_dedupe_key(hit.snippet)
            existing_key = content_keys.get(content_key)
            if existing_key is not None:
                dedupe_key = existing_key
            else:
                content_keys[content_key] = dedupe_key

            fused_scores[dedupe_key] = fused_scores.get(dedupe_key, 0.0) + 1.0 / (_RRF_K + hit.rank)
            previous = by_key.get(dedupe_key)
            if previous is None or _prefer_hit(hit, previous):
                metadata = dict(hit.metadata)
                metadata["rrf_score"] = fused_scores[dedupe_key]
                by_key[dedupe_key] = RetrievalHit(
                    source_type=hit.source_type,
                    source_id=hit.source_id,
                    title=hit.title,
                    snippet=hit.snippet,
                    score=fused_scores[dedupe_key],
                    rank=hit.rank,
                    metadata=metadata,
                )
            else:
                metadata = dict(previous.metadata)
                metadata["rrf_score"] = fused_scores[dedupe_key]
                by_key[dedupe_key] = RetrievalHit(
                    source_type=previous.source_type,
                    source_id=previous.source_id,
                    title=previous.title,
                    snippet=previous.snippet,
                    score=fused_scores[dedupe_key],
                    rank=min(previous.rank, hit.rank),
                    metadata=metadata,
                )

    ranked = sorted(
        by_key.values(),
        key=lambda item: (-item.score, item.rank, item.source_type, item.source_id),
    )
    return ranked[:limit]


def _format_hybrid_display(citations: tuple[Citation, ...]) -> str:
    """摘要：格式化融合结果的展示文本。"""
    if not citations:
        return "（未找到匹配的知识或记忆条目。）"
    lines = ["【融合检索结果】"]
    for citation in citations:
        title = citation.title or "记忆片段"
        lines.append(
            f"[{citation.index}] ({citation.source_type}:{citation.source_id}) {title}\n"
            f"  {citation.snippet}"
        )
    return "\n".join(lines)


def _knowledge_score(value: float | None) -> float:
    """摘要：将知识库 BM25 原始分转为稳定展示分。"""
    if value is None:
        return 0.0
    return 1.0 / (1.0 + abs(float(value)))


def _primary_dedupe_key(hit: RetrievalHit) -> str:
    """摘要：返回同源去重主键。"""
    return f"{hit.source_type}:{hit.source_id}"


def _content_dedupe_key(text: str) -> str:
    """摘要：生成跨库内容哈希去重键。"""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _prefer_hit(candidate: RetrievalHit, current: RetrievalHit) -> bool:
    """摘要：冲突时优先保留信息更完整的一条命中。"""
    candidate_title = 1 if candidate.title else 0
    current_title = 1 if current.title else 0
    candidate_meta = len(candidate.metadata)
    current_meta = len(current.metadata)
    if candidate_title != current_title:
        return candidate_title > current_title
    if candidate_meta != current_meta:
        return candidate_meta > current_meta
    return candidate.rank < current.rank
