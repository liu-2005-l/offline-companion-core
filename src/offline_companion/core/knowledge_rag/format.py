"""format：检索结果展示块（默认不过 B4，保证可核对）。"""

from __future__ import annotations

from .search import KnowledgeSearchHit


def format_knowledge_snippets(hits: list[KnowledgeSearchHit], *, max_chars: int = 1200) -> str:
    """摘要：格式化为终端/日志可读的带来源片段（非模型 prompt）。

    参数：
        hits: 检索命中。
        max_chars: 总字符上限。

    返回值：
        多行文本；无命中时返回提示句。
    """
    if not hits:
        return "（未找到匹配的知识条目。）"
    lines: list[str] = ["【本地知识库检索结果 · 可核对来源】"]
    n = sum(len(x) for x in lines)
    for h in hits:
        line = (
            f"- [来源: {h.source_uri} | 文档#{h.doc_id} 块#{h.chunk_id}] {h.title}\n"
            f"  {h.body}"
        )
        if n + len(line) > max_chars:
            lines.append("- …（更多结果已截断）")
            break
        lines.append(line)
        n += len(line) + 1
    return "\n".join(lines)


def format_knowledge_reference_block(hits: list[KnowledgeSearchHit], *, max_chars: int = 1400) -> str:
    """摘要：格式化为可注入模型的参考块（``answer_after_search`` 时使用）。"""
    if not hits:
        return ""
    lines: list[str] = [
        "【以下为本地知识库检索摘录，仅可引用其中内容；每条均带来源标识】",
        "勿编造未列出的知识；勿声称已联网搜索。",
    ]
    n = sum(len(x) for x in lines)
    for h in hits:
        line = f"- [来源:{h.source_uri}] {h.body}"
        if n + len(line) > max_chars:
            break
        lines.append(line)
        n += len(line) + 1
    return "\n".join(lines)
