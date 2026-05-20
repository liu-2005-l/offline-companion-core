"""search：知识库 FTS 检索。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .audit import log_search


@dataclass(frozen=True)
class KnowledgeSearchHit:
    """摘要：知识检索命中项（含来源，可核对）。"""

    chunk_id: int
    doc_id: int
    title: str
    source_uri: str
    body: str
    score: float | None


def _fts_escape_query(q: str) -> str:
    """摘要：清理 FTS 查询串（勿包短语引号）。"""
    q = q.strip()
    if not q:
        return ""
    for ch in ('"', "*", "(", ")", "-", ":"):
        q = q.replace(ch, " ")
    return " ".join(q.split())


def _search_like(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
) -> list[sqlite3.Row]:
    """摘要：子串回退检索（CJK 在部分平台 FTS5 不建索引时使用）。"""
    q = query.strip()
    if not q:
        return []
    return conn.execute(
        "SELECT c.id AS chunk_id, c.doc_id, c.body, d.title, d.source_uri, NULL AS s "
        "FROM knowledge_chunks AS c "
        "JOIN knowledge_documents AS d ON d.id = c.doc_id "
        "WHERE instr(c.body, ?) > 0 "
        "ORDER BY c.id LIMIT ?;",
        (q, limit),
    ).fetchall()


def search_knowledge(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 5,
    session_id: str | None = None,
) -> list[KnowledgeSearchHit]:
    """摘要：对知识库执行 FTS 检索并写审计日志。

    参数：
        conn: 知识库连接。
        query: 用户查询。
        limit: 返回条数上限。
        session_id: 可选，写入 ``knowledge_search_log``。

    返回值：
        命中列表，含 ``source_uri`` 供展示核对。
    """
    q = _fts_escape_query(query)
    rows: list[sqlite3.Row] = []
    if q:
        try:
            rows = conn.execute(
                "SELECT c.id AS chunk_id, c.doc_id, c.body, d.title, d.source_uri, bm25(knowledge_fts) AS s "
                "FROM knowledge_fts "
                "JOIN knowledge_chunks AS c ON c.id = knowledge_fts.rowid "
                "JOIN knowledge_documents AS d ON d.id = c.doc_id "
                "WHERE knowledge_fts MATCH ? ORDER BY s LIMIT ?;",
                (q, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT c.id AS chunk_id, c.doc_id, c.body, d.title, d.source_uri, NULL AS s "
                "FROM knowledge_fts "
                "JOIN knowledge_chunks AS c ON c.id = knowledge_fts.rowid "
                "JOIN knowledge_documents AS d ON d.id = c.doc_id "
                "WHERE knowledge_fts MATCH ? LIMIT ?;",
                (q, limit),
            ).fetchall()
    if not rows:
        rows = _search_like(conn, query, limit=limit)
    hits = [
        KnowledgeSearchHit(
            chunk_id=int(r["chunk_id"]),
            doc_id=int(r["doc_id"]),
            title=str(r["title"]),
            source_uri=str(r["source_uri"]),
            body=str(r["body"]),
            score=float(r["s"]) if r["s"] is not None else None,
        )
        for r in rows
    ]
    log_search(conn, query=query, hit_ids=[h.chunk_id for h in hits], session_id=session_id)
    return hits
