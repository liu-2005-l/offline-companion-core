"""embedding_config：记忆向量配置加载（B2）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from offline_companion.shared.runtime_paths import configs_dir


@dataclass(frozen=True)
class MemoryEmbeddingConfig:
    """摘要：记忆向量运行时配置。"""

    enabled: bool
    dimensions: int
    blend_weight: float
    min_cosine: float
    config_path: Path


def default_embedding_config_path() -> Path:
    """摘要：默认 ``configs/memory/embedding.yaml`` 路径。"""
    return configs_dir() / "memory" / "embedding.yaml"


def load_embedding_config(path: Path | None = None) -> MemoryEmbeddingConfig:
    """摘要：加载记忆向量配置。

    参数：
        path: YAML 路径；默认仓库内 ``embedding.yaml``。

    返回值：
        ``MemoryEmbeddingConfig``。
    """
    resolved = (path or default_embedding_config_path()).resolve()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    return MemoryEmbeddingConfig(
        enabled=bool(raw.get("enabled", False)),
        dimensions=max(16, int(raw.get("dimensions", 128))),
        blend_weight=min(1.0, max(0.0, float(raw.get("blend_weight", 0.25)))),
        min_cosine=min(1.0, max(0.0, float(raw.get("min_cosine", 0.15)))),
        config_path=resolved,
    )
