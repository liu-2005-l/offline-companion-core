"""摘要：本地确定性向量（哈希袋 + 余弦），无外部模型依赖。"""

from __future__ import annotations

import sqlite3
import time

from offline_companion.shared.deterministic_embedding import (
    blob_to_vector,
    cosine_similarity,
    embed_text,
    tokenize_for_embedding,
    vector_to_blob,
)

from .embedding_config import MemoryEmbeddingConfig, load_embedding_config


def _tokenize_for_embedding(text: str) -> list[str]:
    """摘要：与 recall 一致的分词，避免循环 import。"""
    return tokenize_for_embedding(text)


def maybe_write_embedding(
    conn: sqlite3.Connection,
    chunk_id: int,
    body: str,
    *,
    config: MemoryEmbeddingConfig | None = None,
) -> None:
    """摘要：为已插入的记忆块写入 `embedding_blob`（若配置开启）。"""
    cfg = config or load_embedding_config()
    if not cfg.enabled:
        return
    vec = embed_text(body, dimensions=cfg.dimensions)
    conn.execute(
        "UPDATE memory_chunks SET embedding_blob = ? WHERE id = ?;",
        (vector_to_blob(vec), chunk_id),
    )


def _parse_ts(value: object) -> float:
    """摘要：统一时间解析，兼容数值、ISO 8601 与数字字符串。"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    try:
        return float(text)
    except ValueError:
        try:
            from datetime import datetime

            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return time.time()


def embedding_candidates(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: MemoryEmbeddingConfig | None = None,
    scan_limit: int = 200,
) -> list[tuple[int, str, float, float]]:
    """摘要：扫描带向量的记忆块，返回 `(id, body, cosine, created_at)`。"""
    cfg = config or load_embedding_config()
    if not cfg.enabled or not query.strip():
        return []
    qvec = embed_text(query, dimensions=cfg.dimensions)
    rows = conn.execute(
        "SELECT id, body, embedding_blob, created_at FROM memory_chunks "
        "WHERE status = 'active' AND embedding_blob IS NOT NULL "
        "ORDER BY modified_at DESC LIMIT ?;",
        (scan_limit,),
    ).fetchall()
    out: list[tuple[int, str, float, float]] = []
    for row in rows:
        vec = blob_to_vector(row["embedding_blob"])
        if not vec:
            continue
        sim = cosine_similarity(qvec, vec)
        if sim >= cfg.min_cosine:
            out.append((int(row["id"]), str(row["body"]), sim, _parse_ts(row["created_at"])))
    out.sort(key=lambda item: item[2], reverse=True)
    return out
