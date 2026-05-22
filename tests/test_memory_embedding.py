"""摘要：可选记忆向量（Sprint 5.1）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from offline_companion.core.memory_lifecycle.embedding import cosine_similarity, embed_text
from offline_companion.core.memory_lifecycle.embedding_config import (
    MemoryEmbeddingConfig,
    load_embedding_config,
)
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.recall import recall
from offline_companion.runtime.storage_index.engine import connect, new_session


def _patch_embedding_config(monkeypatch, cfg: MemoryEmbeddingConfig) -> None:
    """摘要：统一替换各模块内的 load_embedding_config。"""
    loader = lambda path=None: cfg  # noqa: E731
    monkeypatch.setattr(
        "offline_companion.core.memory_lifecycle.embedding.load_embedding_config",
        loader,
    )
    monkeypatch.setattr(
        "offline_companion.core.memory_lifecycle.recall.load_embedding_config",
        loader,
    )


def _enabled_config(tmp_path: Path) -> MemoryEmbeddingConfig:
    cfg_path = tmp_path / "embedding.yaml"
    cfg_path.write_text(
        yaml.dump(
            {"version": 1, "enabled": True, "dimensions": 128, "blend_weight": 0.3, "min_cosine": 0.1},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return MemoryEmbeddingConfig(
        enabled=True,
        dimensions=128,
        blend_weight=0.3,
        min_cosine=0.1,
        config_path=cfg_path,
    )


def test_embedding_disabled_no_blob(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "offline_companion.core.memory_lifecycle.embedding.load_embedding_config",
        lambda path=None: MemoryEmbeddingConfig(
            enabled=False,
            dimensions=128,
            blend_weight=0.25,
            min_cosine=0.15,
            config_path=tmp_path / "off.yaml",
        ),
    )
    conn = connect(tmp_path / "e0.db")
    new_session(conn, "s1", "default", title=None)
    mid = MemoryLifecycleManager.add_memory_chunk(conn, "测试记忆", session_id="s1", source="t")
    row = conn.execute(
        "SELECT embedding_blob FROM memory_chunks WHERE id = ?;", (mid,)
    ).fetchone()
    assert row["embedding_blob"] is None


def test_embedding_enabled_writes_blob(tmp_path, monkeypatch) -> None:
    cfg = _enabled_config(tmp_path)
    _patch_embedding_config(monkeypatch, cfg)
    conn = connect(tmp_path / "e1.db")
    new_session(conn, "s1", "default", title=None)
    mid = MemoryLifecycleManager.add_memory_chunk(
        conn, "我对花生过敏", session_id="s1", source="t"
    )
    row = conn.execute(
        "SELECT embedding_blob FROM memory_chunks WHERE id = ?;", (mid,)
    ).fetchone()
    assert row["embedding_blob"] is not None


def test_recall_embedding_boosts_related_chunk(tmp_path, monkeypatch) -> None:
    cfg = _enabled_config(tmp_path)
    _patch_embedding_config(monkeypatch, cfg)
    conn = connect(tmp_path / "e2.db")
    new_session(conn, "s1", "default", title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "我对花生过敏", session_id="s1", source="t")
    hits = recall(conn, "花生酱能吃吗", limit=5)
    assert hits
    assert any("花生" in h.body for h in hits)


def test_cosine_identical() -> None:
    v = embed_text("hello world", dimensions=64)
    assert cosine_similarity(v, v) > 0.99


def test_default_embedding_config_disabled() -> None:
    """仓库默认 YAML 须为 enabled=false（E5）。"""
    cfg = load_embedding_config()
    assert cfg.enabled is False
    assert cfg.dimensions >= 16


def test_recall_default_config_no_embedding_blob(tmp_path) -> None:
    """默认关时写入记忆不产生 embedding_blob。"""
    conn = connect(tmp_path / "e3.db")
    new_session(conn, "s1", "default", title=None)
    mid = MemoryLifecycleManager.add_memory_chunk(conn, "讨厌香菜", session_id="s1", source="t")
    row = conn.execute(
        "SELECT embedding_blob FROM memory_chunks WHERE id = ?;", (mid,)
    ).fetchone()
    assert row["embedding_blob"] is None
    hits = recall(conn, "点菜", limit=5)
    assert hits
    assert any("香菜" in h.body for h in hits)
