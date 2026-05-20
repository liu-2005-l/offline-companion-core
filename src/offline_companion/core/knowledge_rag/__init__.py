"""knowledge_rag：通用知识检索插件（B2 扩展；默认关闭，独立 knowledge.db）。"""

from .config import KnowledgeConfig, load_knowledge_config
from .format import format_knowledge_snippets
from .ingest import ingest_jsonl_file
from .search import KnowledgeSearchHit, search_knowledge

__all__ = [
    "KnowledgeConfig",
    "KnowledgeSearchHit",
    "format_knowledge_snippets",
    "ingest_jsonl_file",
    "load_knowledge_config",
    "search_knowledge",
]
