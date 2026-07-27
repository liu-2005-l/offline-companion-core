"""recall：主动记忆召回（FTS + 关键词补强 + 时间衰减 + 情绪加权）。"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from typing import Any

import yaml

from offline_companion.shared.runtime_paths import configs_dir, dev_repo_root
from offline_companion.shared.types import MemoryRecallHit

from .embedding import embedding_candidates
from .embedding_config import load_embedding_config

_DEFAULT_HALF_LIFE_SEC = 30.0 * 86400.0
_EMOTION_RECALL_BOOSTS: dict[str, float] | None = None


def _fts_escape_query(query: str) -> str:
    query = query.strip()
    if not query:
        return ""
    query = query.replace('"', " ")
    return f'"{query}"'


def _load_emotion_recall_boosts() -> dict[str, float]:
    """摘要：加载情绪召回加权配置。"""
    global _EMOTION_RECALL_BOOSTS
    if _EMOTION_RECALL_BOOSTS is not None:
        return _EMOTION_RECALL_BOOSTS
    candidates = [
        configs_dir() / "emotion_recall_boost.yaml",
        dev_repo_root() / "configs" / "emotion_recall_boost.yaml",
    ]
    boosts: dict[str, float] = {"exact_match": 1.2, "no_match": 1.0}
    for path in candidates:
        if not path.is_file():
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        section = raw.get("boosts", {}) if isinstance(raw, dict) else {}
        if not isinstance(section, dict):
            continue
        exact_match = section.get("exact_match", boosts["exact_match"])
        no_match = section.get("no_match", boosts["no_match"])
        boosts = {
            "exact_match": float(exact_match),
            "no_match": float(no_match),
        }
        break
    _EMOTION_RECALL_BOOSTS = boosts
    return boosts


def _tokenize_for_overlap(text: str) -> list[str]:
    """摘要：提取查询中的英文词元与 CJK 片段，用于关键词重叠补强。"""
    text = text.strip().lower()
    if not text:
        return []
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) >= 2:
            tokens.append(word)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend(cjk)
    for index in range(len(cjk) - 1):
        tokens.append(cjk[index] + cjk[index + 1])
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _bm25_to_relevance(bm25_score: float | None) -> float:
    """摘要：将 FTS5 bm25 原始分转换为稳定相关度。"""
    if bm25_score is None:
        return 0.5
    return 1.0 / (1.0 + abs(float(bm25_score)))


def _parse_ts(value: Any) -> float:
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


def _time_decay(created_at: float, now: float, half_life_sec: float) -> float:
    age = max(0.0, now - created_at)
    if half_life_sec <= 0:
        return 1.0
    return math.exp(-age / half_life_sec * math.log(2.0))


def _emotion_boost(meta_json: str | None, emotion: str | None) -> float:
    """摘要：按当前情绪对记忆召回分数做精确标签加权。"""
    boosts = _load_emotion_recall_boosts()
    if not emotion:
        return boosts["no_match"]
    try:
        meta = json.loads(meta_json or "{}")
    except json.JSONDecodeError:
        return boosts["no_match"]
    stored = str(meta.get("emotion") or "").strip().lower()
    if stored and stored == emotion.strip().lower():
        return boosts["exact_match"]
    return boosts["no_match"]


def _build_matched_on(
    *,
    match_type: str,
    matched_keywords: list[str],
    fts_score: float | None,
    age_days: float,
    decay_factor: float,
    emotion_boost: float,
) -> dict[str, Any]:
    if matched_keywords:
        keyword_summary = "、".join(f"“{keyword}”" for keyword in matched_keywords[:5])
        summary = f"关键词 {keyword_summary} 命中记忆正文"
    elif match_type == "fts":
        summary = "全文检索（FTS）命中当前问题"
    elif match_type == "embedding":
        summary = "向量相似度与当前问题接近"
    else:
        summary = "与当前问题相关"
    return {
        "summary": summary,
        "match_type": match_type,
        "matched_keywords": matched_keywords,
        "fts_score": fts_score,
        "age_days": round(age_days, 2),
        "decay_factor": round(decay_factor, 4),
        "emotion_boost": round(emotion_boost, 4),
    }


def recall(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 8,
    half_life_sec: float = _DEFAULT_HALF_LIFE_SEC,
    candidate_multiplier: int = 5,
    emotion: str | None = None,
) -> list[MemoryRecallHit]:
    """摘要：主动召回与当前输入相关的已保存记忆。

    参数:
        conn: SQLite 连接。
        query: 当前用户输入。
        limit: 返回条数上限。
        half_life_sec: 时间衰减半衰期（秒）。
        candidate_multiplier: FTS 候选池相对 limit 的倍数。
        emotion: 当前用户情绪标签；命中相同情绪的记忆会获得额外加权。

    返回值:
        按 ``combined_score`` 降序排列的 ``MemoryRecallHit`` 列表。
    """
    query = query.strip()
    if not query:
        return []

    now = time.time()
    by_id: dict[int, MemoryRecallHit] = {}
    overlap_tokens = _tokenize_for_overlap(query)
    fts_query = _fts_escape_query(query)
    if fts_query:
        pool = max(limit * candidate_multiplier, limit)
        try:
            rows = conn.execute(
                "SELECT m.id, m.body, m.created_at, m.meta_json, bm25(memory_fts) AS s "
                "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
                "WHERE memory_fts MATCH ? AND m.status = 'active' ORDER BY s LIMIT ?;",
                (fts_query, pool),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT m.id, m.body, m.created_at, m.meta_json, NULL AS s "
                "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
                "WHERE memory_fts MATCH ? AND m.status = 'active' LIMIT ?;",
                (fts_query, pool),
            ).fetchall()

        for row in rows:
            memory_id = int(row["id"])
            created_at = _parse_ts(row["created_at"])
            fts_score = row["s"]
            relevance = _bm25_to_relevance(fts_score)
            decay = _time_decay(created_at, now, half_life_sec)
            boost = _emotion_boost(row["meta_json"], emotion)
            combined = relevance * decay * boost
            matched_keywords = [token for token in overlap_tokens if token in str(row["body"]).lower()]
            by_id[memory_id] = MemoryRecallHit(
                id=memory_id,
                body=str(row["body"]),
                created_at=created_at,
                combined_score=combined,
                decay_factor=decay,
                matched_on=_build_matched_on(
                    match_type="fts",
                    matched_keywords=matched_keywords,
                    fts_score=float(fts_score) if fts_score is not None else None,
                    age_days=(now - created_at) / 86400.0,
                    decay_factor=decay,
                    emotion_boost=boost,
                ),
            )

    if len(by_id) < limit and overlap_tokens:
        rows = conn.execute(
            "SELECT id, body, created_at, meta_json "
            "FROM memory_chunks WHERE status = 'active' "
            "ORDER BY modified_at DESC, id DESC LIMIT 200;"
        ).fetchall()
        for row in rows:
            memory_id = int(row["id"])
            if memory_id in by_id:
                continue
            body_lower = str(row["body"]).lower()
            matched_keywords = [token for token in overlap_tokens if token in body_lower]
            if not matched_keywords:
                continue
            created_at = _parse_ts(row["created_at"])
            relevance = min(1.0, 0.35 + 0.15 * len(matched_keywords))
            decay = _time_decay(created_at, now, half_life_sec)
            boost = _emotion_boost(row["meta_json"], emotion)
            combined = relevance * decay * boost
            by_id[memory_id] = MemoryRecallHit(
                id=memory_id,
                body=str(row["body"]),
                created_at=created_at,
                combined_score=combined,
                decay_factor=decay,
                matched_on=_build_matched_on(
                    match_type="keyword_overlap",
                    matched_keywords=matched_keywords,
                    fts_score=None,
                    age_days=(now - created_at) / 86400.0,
                    decay_factor=decay,
                    emotion_boost=boost,
                ),
            )

    embedding_config = load_embedding_config()
    if embedding_config.enabled:
        for memory_id, body, similarity, created_at in embedding_candidates(conn, query, config=embedding_config):
            decay = _time_decay(created_at, now, half_life_sec)
            embedding_relevance = similarity * embedding_config.blend_weight
            combined = embedding_relevance * decay
            if memory_id in by_id:
                hit = by_id[memory_id]
                matched_on = dict(hit.matched_on)
                matched_on["match_type"] = "fts+embedding" if hit.matched_on.get("match_type") == "fts" else "embedding"
                matched_on["embedding_cosine"] = round(similarity, 4)
                by_id[memory_id] = MemoryRecallHit(
                    id=memory_id,
                    body=hit.body,
                    created_at=hit.created_at,
                    combined_score=max(hit.combined_score, combined),
                    decay_factor=hit.decay_factor,
                    matched_on=matched_on,
                )
            else:
                by_id[memory_id] = MemoryRecallHit(
                    id=memory_id,
                    body=body,
                    created_at=created_at,
                    combined_score=combined,
                    decay_factor=decay,
                    matched_on={
                        **_build_matched_on(
                            match_type="embedding",
                            matched_keywords=[],
                            fts_score=None,
                            age_days=(now - created_at) / 86400.0,
                            decay_factor=decay,
                            emotion_boost=1.0,
                        ),
                        "embedding_cosine": round(similarity, 4),
                    },
                )

    ranked = sorted(by_id.values(), key=lambda hit: hit.combined_score, reverse=True)
    return ranked[:limit]


_TABOO_BODY_MARKERS = (
    "讨厌",
    "不喜欢",
    "不要",
    "别放",
    "忌口",
    "禁忌",
    "过敏",
    "不能吃",
    "不爱吃",
    "避免",
    "拒绝",
)


def _memory_has_taboo_signal(body: str) -> bool:
    """摘要：判断记忆正文是否表达偏好/禁忌。"""
    text = body.strip()
    if not text:
        return False
    return any(marker in text for marker in _TABOO_BODY_MARKERS)


_PREFERENCE_CONSTRAINT_BLOCK = (
    "\n\n"
    "【重要提醒：用户偏好与禁忌】\n"
    "如果上述记忆中包含用户的偏好、禁忌、过敏、讨厌、不要或类似表述，"
    "你在回答时必须严格遵守，不得推荐、建议或提及被禁止的事项。"
    "如需给出相关建议，请主动提供替代方案。"
    "例如：用户表示“讨厌香菜”，则所有涉及食材、菜品的建议中都不得出现香菜。"
)

_ANSWER_DIRECTIVE_BLOCK = (
    "\n\n"
    "【回答要求】\n"
    "若上述记忆与当前用户问题直接相关，必须根据记忆作答（可自然说“记得你说过……”），"
    "不要重复对话历史中无关寒暄，也不要说不知道。"
)

_RECALL_TRAILING_BLOCKS = _PREFERENCE_CONSTRAINT_BLOCK + _ANSWER_DIRECTIVE_BLOCK


def format_recall_prompt_block(hits: list[MemoryRecallHit], max_chars: int = 1400) -> str:
    """摘要：将召回结果格式化为可注入模型的记忆块。

    参数:
        hits: 召回命中列表。
        max_chars: 记忆块最大字符数（含尾部固定约束）。

    返回值:
        可拼接进 system/user 上下文的记忆块；无命中时返回空字符串。
    """
    if not hits:
        return ""
    lines: list[str] = [
        "【用户此前主动保存的信息，仅供参考；勿编造未列出内容。】",
        "若与当前话题相关，可自然引用（例如“记得你说过……”），勿当作刚发生的事实陈述。",
    ]
    char_count = sum(len(line) for line in lines)
    for hit in hits:
        summary = str(hit.matched_on.get("summary") or "")
        body = hit.body.strip()
        taboo = _memory_has_taboo_signal(body)
        prefix = "【禁忌】" if taboo else ""
        line = f"- (记忆#{hit.id}) {prefix}{body}".strip()
        if summary:
            line += f"\n  为何想起：{summary}；时间衰减系数 {hit.decay_factor:.2f}"
        if taboo:
            line += "\n  要求：回复中不得建议或包含本条禁止内容。"
        if char_count + len(line) > max_chars:
            break
        lines.append(line)
        char_count += len(line) + 1
    body_text = "\n".join(lines)
    combined = body_text + _RECALL_TRAILING_BLOCKS
    if len(combined) <= max_chars:
        return combined
    budget = max(0, max_chars - len(_RECALL_TRAILING_BLOCKS))
    if budget <= 0:
        return _RECALL_TRAILING_BLOCKS.strip()
    trimmed = body_text[:budget].rstrip()
    return trimmed + _RECALL_TRAILING_BLOCKS
