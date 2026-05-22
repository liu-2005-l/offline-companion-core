"""embedding：本地确定性向量（哈希袋 + 余弦；无外部模型）。"""

from __future__ import annotations

import json
import math
import re
import sqlite3

from .embedding_config import MemoryEmbeddingConfig, load_embedding_config


def _tokenize_for_embedding(text: str) -> list[str]:
    """摘要：与 recall 一致的分词，避免循环 import。"""
    text = text.strip().lower()
    if not text:
        return []
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) >= 2:
            tokens.append(word)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend(cjk)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def embed_text(text: str, *, dimensions: int) -> list[float]:
    """摘要：将文本编码为 L2 归一化哈希袋向量。

    参数：
        text: 记忆或查询正文。
        dimensions: 向量维度。

    返回值：
        浮点列表，长度 ``dimensions``。
    """
    vec = [0.0] * dimensions
    text_l = text.strip().lower()
    if not text_l:
        return vec
    tokens = _tokenize_for_embedding(text_l)
    cjk = re.findall(r"[\u4e00-\u9fff]", text_l)
    tokens.extend(cjk)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    for t in tokens:
        if not t:
            continue
        idx = hash(t) % dimensions
        vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def vector_to_blob(vec: list[float]) -> bytes:
    """摘要：序列化向量存入 BLOB。"""
    return json.dumps(vec, ensure_ascii=False).encode("utf-8")


def blob_to_vector(blob: bytes | None) -> list[float] | None:
    """摘要：从 BLOB 反序列化向量。"""
    if not blob:
        return None
    try:
        data = json.loads(blob.decode("utf-8"))
        if isinstance(data, list) and data:
            return [float(x) for x in data]
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return None
    return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """摘要：余弦相似度；维度不一致时返回 0。"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def maybe_write_embedding(
    conn: sqlite3.Connection,
    chunk_id: int,
    body: str,
    *,
    config: MemoryEmbeddingConfig | None = None,
) -> None:
    """摘要：为已插入的记忆块写入 ``embedding_blob``（若配置开启）。"""
    cfg = config or load_embedding_config()
    if not cfg.enabled:
        return
    vec = embed_text(body, dimensions=cfg.dimensions)
    conn.execute(
        "UPDATE memory_chunks SET embedding_blob = ? WHERE id = ?;",
        (vector_to_blob(vec), chunk_id),
    )


def embedding_candidates(
    conn: sqlite3.Connection,
    query: str,
    *,
    config: MemoryEmbeddingConfig | None = None,
    scan_limit: int = 200,
) -> list[tuple[int, str, float, float]]:
    """摘要：扫描带向量的记忆块，返回 (id, body, cosine, created_at)。"""
    cfg = config or load_embedding_config()
    if not cfg.enabled or not query.strip():
        return []
    qvec = embed_text(query, dimensions=cfg.dimensions)
    rows = conn.execute(
        "SELECT id, body, embedding_blob, created_at FROM memory_chunks "
        "WHERE embedding_blob IS NOT NULL ORDER BY updated_at DESC LIMIT ?;",
        (scan_limit,),
    ).fetchall()
    out: list[tuple[int, str, float, float]] = []
    for r in rows:
        vec = blob_to_vector(r["embedding_blob"])
        if not vec:
            continue
        sim = cosine_similarity(qvec, vec)
        if sim >= cfg.min_cosine:
            out.append((int(r["id"]), str(r["body"]), sim, float(r["created_at"])))
    out.sort(key=lambda x: x[2], reverse=True)
    return out
