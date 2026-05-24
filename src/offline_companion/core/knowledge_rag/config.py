"""config：知识 RAG YAML 配置加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class KnowledgeConfig:
    """摘要：知识插件运行时配置。"""

    enabled: bool
    top_k: int
    max_snippet_chars: int
    answer_after_search: bool
    db_path: Path | None
    config_path: Path


from offline_companion.shared.runtime_paths import configs_dir


def default_knowledge_config_path() -> Path:
    """摘要：默认 ``configs/knowledge/default.yaml`` 路径。"""
    return configs_dir() / "knowledge" / "default.yaml"


def load_knowledge_config(path: Path | None = None) -> KnowledgeConfig:
    """摘要：加载知识配置。

    参数：
        path: YAML 路径；默认仓库内 default.yaml。

    返回值：
        ``KnowledgeConfig``。
    """
    resolved = (path or default_knowledge_config_path()).resolve()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    db_raw = raw.get("db_path")
    db_path = Path(str(db_raw)).expanduser() if db_raw else None
    return KnowledgeConfig(
        enabled=bool(raw.get("enabled", False)),
        top_k=int(raw.get("top_k", 5)),
        max_snippet_chars=int(raw.get("max_snippet_chars", 1200)),
        answer_after_search=bool(raw.get("answer_after_search", False)),
        db_path=db_path,
        config_path=resolved,
    )
