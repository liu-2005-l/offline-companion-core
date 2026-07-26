"""摘要：跨层可复用的确定性文本向量工具。"""

from __future__ import annotations

import json
import math
import re


def tokenize_for_embedding(text: str) -> list[str]:
    """摘要：对中英混合文本做稳定分词，供确定性向量使用。"""
    normalized = text.strip().lower()
    if not normalized:
        return []
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+", normalized):
        if len(word) >= 2:
            tokens.append(word)
    cjk = re.findall(r"[\u4e00-\u9fff]", normalized)
    tokens.extend(cjk)
    for index in range(len(cjk) - 1):
        tokens.append(cjk[index] + cjk[index + 1])
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped


def embed_text(text: str, *, dimensions: int) -> list[float]:
    """摘要：将文本编码为 L2 归一化的确定性哈希袋向量。"""
    vec = [0.0] * dimensions
    for token in tokenize_for_embedding(text):
        idx = hash(token) % dimensions
        vec[idx] += 1.0
    norm = math.sqrt(sum(value * value for value in vec))
    if norm <= 0:
        return vec
    return [value / norm for value in vec]


def vector_to_blob(vec: list[float]) -> bytes:
    """摘要：将向量序列化为 UTF-8 JSON BLOB。"""
    return json.dumps(vec, ensure_ascii=False).encode("utf-8")


def blob_to_vector(blob: bytes | None) -> list[float] | None:
    """摘要：从 UTF-8 JSON BLOB 反序列化向量。"""
    if not blob:
        return None
    try:
        data = json.loads(blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, list) or not data:
        return None
    try:
        return [float(item) for item in data]
    except (TypeError, ValueError):
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """摘要：计算两个等长向量的余弦相似度。"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)
