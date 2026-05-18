"""recall：主动记忆召回（FTS + 关键词补强 + 时间衰减 + matched_on）。"""

from __future__ import annotations

import math
import re
import sqlite3
import time
from typing import Any

from offline_companion.shared.types import MemoryRecallHit

# 半衰期（秒）：越久未更新/创建的记忆权重越低
_DEFAULT_HALF_LIFE_SEC = 30.0 * 86400.0


def _fts_escape_query(q: str) -> str:
    q = q.strip()
    if not q:
        return ""
    q = q.replace('"', " ")
    return f'"{q}"'


def _tokenize_for_overlap(text: str) -> list[str]:
    """摘要：从查询中提取可用于重叠匹配的词元（中英文混合）。"""
    text = text.strip().lower()
    if not text:
        return []
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) >= 2:
            tokens.append(word)
    # 中文：连续 CJK 字符的单字与二字片段，提高「菜」类短词命中率
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend(cjk)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _bm25_to_relevance(bm25_score: float | None) -> float:
    """摘要：将 SQLite bm25 分值转为 [0,1] 相关性（越大越好）。"""
    if bm25_score is None:
        return 0.5
    # FTS5 bm25 通常为负，绝对值越小（越接近 0）越相关
    return 1.0 / (1.0 + abs(float(bm25_score)))


def _time_decay(created_at: float, now: float, half_life_sec: float) -> float:
    age = max(0.0, now - created_at)
    if half_life_sec <= 0:
        return 1.0
    return math.exp(-age / half_life_sec * math.log(2.0))


def _build_matched_on(
    *,
    match_type: str,
    matched_keywords: list[str],
    fts_score: float | None,
    age_days: float,
    decay_factor: float,
) -> dict[str, Any]:
    if matched_keywords:
        kw = "、".join(f"「{k}」" for k in matched_keywords[:5])
        summary = f"关键词 {kw} 命中记忆正文"
    elif match_type == "fts":
        summary = "全文检索（FTS）命中当前问题"
    else:
        summary = "与当前问题相关"
    return {
        "summary": summary,
        "match_type": match_type,
        "matched_keywords": matched_keywords,
        "fts_score": fts_score,
        "age_days": round(age_days, 2),
        "decay_factor": round(decay_factor, 4),
    }


def recall(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 8,
    half_life_sec: float = _DEFAULT_HALF_LIFE_SEC,
    candidate_multiplier: int = 5,
) -> list[MemoryRecallHit]:
    """摘要：主动召回与用户输入相关的已保存记忆（仅读显式写入条目）。

    参数：
        conn: SQLite 连接。
        query: 当前用户输入。
        limit: 返回条数上限。
        half_life_sec: 时间衰减半衰期（秒）。
        candidate_multiplier: FTS 候选池相对 limit 的倍数。

    返回值：
        按 ``combined_score`` 降序排列的 ``MemoryRecallHit`` 列表。
    """
    query = query.strip()
    if not query:
        return []

    now = time.time()
    by_id: dict[int, MemoryRecallHit] = {}

    fts_q = _fts_escape_query(query)
    if fts_q:
        pool = max(limit * candidate_multiplier, limit)
        try:
            rows = conn.execute(
                "SELECT m.id, m.body, m.created_at, bm25(memory_fts) AS s "
                "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
                "WHERE memory_fts MATCH ? ORDER BY s LIMIT ?;",
                (fts_q, pool),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT m.id, m.body, m.created_at, NULL AS s "
                "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
                "WHERE memory_fts MATCH ? LIMIT ?;",
                (fts_q, pool),
            ).fetchall()

        for r in rows:
            mid = int(r["id"])
            created = float(r["created_at"])
            fts_s = r["s"]
            rel = _bm25_to_relevance(fts_s)
            decay = _time_decay(created, now, half_life_sec)
            combined = rel * decay
            kws = [t for t in _tokenize_for_overlap(query) if t in str(r["body"]).lower()]
            by_id[mid] = MemoryRecallHit(
                id=mid,
                body=str(r["body"]),
                created_at=created,
                combined_score=combined,
                decay_factor=decay,
                matched_on=_build_matched_on(
                    match_type="fts",
                    matched_keywords=kws,
                    fts_score=float(fts_s) if fts_s is not None else None,
                    age_days=(now - created) / 86400.0,
                    decay_factor=decay,
                ),
            )

  # 关键词补强：FTS 漏检时（如「食物」与「香菜」），用重叠词元扫描近期记忆
    if len(by_id) < limit:
        tokens = _tokenize_for_overlap(query)
        if tokens:
            rows = conn.execute(
                "SELECT id, body, created_at FROM memory_chunks ORDER BY updated_at DESC LIMIT 200;"
            ).fetchall()
            for r in rows:
                mid = int(r["id"])
                if mid in by_id:
                    continue
                body_l = str(r["body"]).lower()
                matched = [t for t in tokens if t in body_l]
                if not matched:
                    continue
                created = float(r["created_at"])
                rel = min(1.0, 0.35 + 0.15 * len(matched))
                decay = _time_decay(created, now, half_life_sec)
                combined = rel * decay
                by_id[mid] = MemoryRecallHit(
                    id=mid,
                    body=str(r["body"]),
                    created_at=created,
                    combined_score=combined,
                    decay_factor=decay,
                    matched_on=_build_matched_on(
                        match_type="keyword_overlap",
                        matched_keywords=matched,
                        fts_score=None,
                        age_days=(now - created) / 86400.0,
                        decay_factor=decay,
                    ),
                )

    ranked = sorted(by_id.values(), key=lambda h: h.combined_score, reverse=True)
    return ranked[:limit]


# 偏好/禁忌类记忆的正文标记（用于逐条【禁忌】标记，非 B3 安全分级）
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
    """摘要：判断记忆正文是否表达偏好/禁忌（需模型严格遵守）。"""
    text = body.strip()
    if not text:
        return False
    return any(m in text for m in _TABOO_BODY_MARKERS)


# 有记忆召回时始终追加（小模型对固定尾部指令跟随优于条件注入）
_PREFERENCE_CONSTRAINT_BLOCK = (
    "\n\n"
    "【重要提醒：用户偏好与禁忌】\n"
    "如果上述记忆中包含用户的偏好、禁忌、过敏、讨厌、不要或类似表述，"
    "你在回答时必须严格遵守，不得推荐、建议或提及被禁止的事项。"
    "如需给出相关建议，请主动提供替代方案。"
    "例如：用户表示「讨厌香菜」，则所有涉及食物、菜品的建议中都不得出现香菜。"
)


def format_recall_prompt_block(hits: list[MemoryRecallHit], max_chars: int = 1400) -> str:
    """摘要：将召回结果格式化为可注入模型的「你可能想起来的」记忆块。

    参数：
        hits: 召回命中列表。
        max_chars: 记忆块最大字符数（含固定约束段）。

    返回值：
        可拼入 system/user 上下文的记忆块；无命中时返回空字符串。
    """
    if not hits:
        return ""
    lines: list[str] = [
        "【用户此前主动保存的信息，仅供参考；勿编造未列出内容】",
        "若与当前话题相关，可自然引用（例如「记得你说过……」），勿当作刚发生的事实陈述。",
    ]
    n = sum(len(x) for x in lines)
    for h in hits:
        summary = str(h.matched_on.get("summary") or "")
        body = h.body.strip()
        taboo = _memory_has_taboo_signal(body)
        prefix = "【禁忌】" if taboo else ""
        line = f"- (记忆#{h.id}) {prefix}{body}".strip()
        if summary:
            line += f"\n  为何想起：{summary}；时间衰减系数 {h.decay_factor:.2f}"
        if taboo:
            line += "\n  要求：回复中不得建议或包含本条禁止内容。"
        if n + len(line) > max_chars:
            break
        lines.append(line)
        n += len(line) + 1
    body_text = "\n".join(lines)
    combined = body_text + _PREFERENCE_CONSTRAINT_BLOCK
    if len(combined) <= max_chars:
        return combined
    # 超长时仍保留约束段，截断条目部分
    budget = max(0, max_chars - len(_PREFERENCE_CONSTRAINT_BLOCK))
    if budget <= 0:
        return _PREFERENCE_CONSTRAINT_BLOCK.strip()
    trimmed = body_text[:budget].rstrip()
    return trimmed + _PREFERENCE_CONSTRAINT_BLOCK
