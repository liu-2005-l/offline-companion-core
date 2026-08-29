from __future__ import annotations

import logging
import math
import sqlite3
import time
from pathlib import Path

from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import (
    CONTENT_EMBEDDING_DIMENSIONS,
    SemanticEvent,
)
from offline_companion.core.memory_lifecycle.semantic_embedding_provider import (
    SemanticEmbeddingModelPaths,
    SemanticEmbeddingProvider,
    reset_semantic_embedding_fallback_warning,
)


def _event(event_id: str, content: str, vector: list[float]) -> SemanticEvent:
    return SemanticEvent(
        event_id=event_id,
        event_type="fact",
        subject="user",
        content=content,
        content_embedding=vector,
        created_at=time.time(),
    )


def test_semantic_embedding_provider_falls_back_with_one_warning(
    tmp_path: Path,
    caplog,
) -> None:
    """摘要：无 ONNX 模型时语义事件 embedding 回退 hash-bow 且 warning 只打一遍。"""
    reset_semantic_embedding_fallback_warning()
    provider = SemanticEmbeddingProvider(data_root=tmp_path)

    with caplog.at_level(
        logging.WARNING,
        logger="offline_companion.core.memory_lifecycle.semantic_embedding_provider",
    ):
        first = provider("布丁喜欢逗猫棒")
        second = provider("布丁喜欢逗猫棒")

    assert first == second
    assert len(first) == CONTENT_EMBEDDING_DIMENSIONS
    assert provider.embedding_space == "hash_bow_768"
    assert provider.preferred_embedding_space == "hash_bow_768"
    assert caplog.text.count("falling back to hash-bow") == 1


def test_semantic_embedding_provider_uses_onnx_and_normalizes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """摘要：ONNX 路返回原生 768 维归一化向量，不走 hash-bow 降级。"""

    class _Input:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Session:
        def __init__(self, _path: str, providers: list[str]) -> None:
            assert providers == ["CPUExecutionProvider"]

        def get_inputs(self) -> list[_Input]:
            return [_Input("input_ids"), _Input("attention_mask"), _Input("token_type_ids")]

        def run(self, _names, feeds):
            assert "input_ids" in feeds
            assert "attention_mask" in feeds
            assert "token_type_ids" in feeds
            values = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
            values[0] = 3.0
            values[1] = 4.0
            return [[values]]

    class _Ort:
        InferenceSession = _Session

    class _Encoded:
        ids = [1, 2]
        attention_mask = [1, 1]

    class _Tokenizer:
        @classmethod
        def from_file(cls, _path: str):
            return cls()

        def encode(self, _text: str) -> _Encoded:
            return _Encoded()

    import offline_companion.core.memory_lifecycle.semantic_embedding_provider as module

    monkeypatch.setattr(module, "ort", _Ort)
    monkeypatch.setattr(module, "Tokenizer", _Tokenizer)
    model_path = tmp_path / "model.onnx"
    tokenizer_path = tmp_path / "tokenizer.json"
    model_path.write_bytes(b"model")
    tokenizer_path.write_text("{}", encoding="utf-8")
    provider = SemanticEmbeddingProvider(
        model_paths=SemanticEmbeddingModelPaths(model_path, tokenizer_path),
        fallback=lambda _text: [0.0] * CONTENT_EMBEDDING_DIMENSIONS,
    )

    vector = provider("任意文本")

    assert vector[0] == 0.6
    assert vector[1] == 0.8
    assert provider.embedding_space == "semantic_onnx_768"
    assert provider.preferred_embedding_space == "semantic_onnx_768"
    assert math.isclose(sum(value * value for value in vector), 1.0)


def test_semantic_embedding_provider_uses_cls_for_token_embeddings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """摘要：BGE 3D token 输出使用 CLS 向量，避免 mean pooling 漂移。"""

    class _Input:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Session:
        def __init__(self, _path: str, providers: list[str]) -> None:
            del providers

        def get_inputs(self) -> list[_Input]:
            return [_Input("input_ids"), _Input("attention_mask")]

        def run(self, _names, _feeds):
            cls = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
            other = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
            cls[0] = 1.0
            other[1] = 1.0
            return [[[cls, other]]]

    class _Ort:
        InferenceSession = _Session

    class _Encoded:
        ids = [1, 2]
        attention_mask = [1, 1]

    class _Tokenizer:
        @classmethod
        def from_file(cls, _path: str):
            return cls()

        def encode(self, _text: str) -> _Encoded:
            return _Encoded()

    import offline_companion.core.memory_lifecycle.semantic_embedding_provider as module

    monkeypatch.setattr(module, "ort", _Ort)
    monkeypatch.setattr(module, "Tokenizer", _Tokenizer)
    model_path = tmp_path / "model.onnx"
    tokenizer_path = tmp_path / "tokenizer.json"
    model_path.write_bytes(b"model")
    tokenizer_path.write_text("{}", encoding="utf-8")

    vector = SemanticEmbeddingProvider(
        model_paths=SemanticEmbeddingModelPaths(model_path, tokenizer_path)
    )("任意文本")

    assert vector[0] == 1.0
    assert vector[1] == 0.0


def test_semantic_embedding_provider_reuses_loaded_model_handles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """摘要：同一 provider 多次调用复用 ONNX session 与 tokenizer，避免每轮重载模型。"""
    session_loads = 0
    tokenizer_loads = 0

    class _Input:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Session:
        def __init__(self, _path: str, providers: list[str]) -> None:
            nonlocal session_loads
            del providers
            session_loads += 1

        def get_inputs(self) -> list[_Input]:
            return [_Input("input_ids"), _Input("attention_mask")]

        def run(self, _names, _feeds):
            values = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
            values[0] = 1.0
            return [[values]]

    class _Ort:
        InferenceSession = _Session

    class _Encoded:
        ids = [1]
        attention_mask = [1]

    class _Tokenizer:
        @classmethod
        def from_file(cls, _path: str):
            nonlocal tokenizer_loads
            tokenizer_loads += 1
            return cls()

        def encode(self, _text: str) -> _Encoded:
            return _Encoded()

    import offline_companion.core.memory_lifecycle.semantic_embedding_provider as module

    monkeypatch.setattr(module, "ort", _Ort)
    monkeypatch.setattr(module, "Tokenizer", _Tokenizer)
    model_path = tmp_path / "model.onnx"
    tokenizer_path = tmp_path / "tokenizer.json"
    model_path.write_bytes(b"model")
    tokenizer_path.write_text("{}", encoding="utf-8")
    provider = SemanticEmbeddingProvider(
        model_paths=SemanticEmbeddingModelPaths(model_path, tokenizer_path)
    )

    assert provider("第一次")[0] == 1.0
    assert provider("第二次")[0] == 1.0
    assert session_loads == 1
    assert tokenizer_loads == 1


def test_repository_recomputes_all_content_embeddings(tmp_path: Path) -> None:
    """摘要：启动期重算用统一入口覆盖旧库，避免 hash-bow 与 semantic 混源。"""
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    old_vector = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
    old_vector[0] = 1.0
    repo.store(_event("a", "第一条", old_vector))
    repo.store(_event("b", "第二条", old_vector))

    class _SemanticEmbedder:
        preferred_embedding_space = "semantic_onnx_768"
        embedding_space = "semantic_onnx_768"

        def __call__(self, content: str) -> list[float]:
            values = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
            values[1 if content == "第一条" else 2] = 1.0
            return values

    result = repo.recompute_content_embeddings(_SemanticEmbedder())

    assert result == {"total": 2, "updated": 2, "failed": 0}
    assert repo.get("a").content_embedding[1] == 1.0
    assert repo.get("a").content_embedding_space == "semantic_onnx_768"
    assert repo.get("b").content_embedding[2] == 1.0


def test_repository_recomputes_only_mismatched_embedding_space(tmp_path: Path) -> None:
    """摘要：重算只处理目标空间不匹配的行，保留已完成行的幂等边界。"""
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    semantic_vector = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
    semantic_vector[3] = 1.0
    repo.store(
        SemanticEvent(
            event_id="done",
            event_type="fact",
            subject="user",
            content="已完成",
            content_embedding=semantic_vector,
            content_embedding_space="semantic_onnx_768",
            created_at=time.time(),
        )
    )
    repo.store(_event("old", "旧空间", semantic_vector))

    class _SemanticEmbedder:
        preferred_embedding_space = "semantic_onnx_768"
        embedding_space = "semantic_onnx_768"

        def __call__(self, _content: str) -> list[float]:
            values = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
            values[4] = 1.0
            return values

    result = repo.recompute_content_embeddings(_SemanticEmbedder())

    assert result == {"total": 1, "updated": 1, "failed": 0}
    assert repo.get("done").content_embedding[3] == 1.0
    assert repo.get("old").content_embedding[4] == 1.0


def test_repository_failed_recompute_keeps_none_space_for_bounded_retry(tmp_path: Path) -> None:
    """摘要：重算失败写入 none 空间，后续只作为有界重试目标而不产生混源分数。"""
    repo = EventRepository(sqlite3.connect(tmp_path / "events.db"))
    semantic_vector = [0.0] * CONTENT_EMBEDDING_DIMENSIONS
    semantic_vector[3] = 1.0
    repo.store(
        SemanticEvent(
            event_id="broken",
            event_type="fact",
            subject="user",
            content="失败向量",
            content_embedding=semantic_vector,
            content_embedding_space="hash_bow_768",
            created_at=time.time(),
        )
    )

    class _BrokenEmbedder:
        preferred_embedding_space = "semantic_onnx_768"

        def __call__(self, _content: str) -> list[float]:
            raise RuntimeError("model crashed")

    first = repo.recompute_content_embeddings(_BrokenEmbedder())
    second = repo.recompute_content_embeddings(_BrokenEmbedder())

    stored = repo.get("broken")
    assert first == {"total": 1, "updated": 1, "failed": 1}
    assert second == {"total": 1, "updated": 1, "failed": 1}
    assert stored.content_embedding is None
    assert stored.content_embedding_space == "none"
    assert repo.vector_search(semantic_vector, embedding_space="semantic_onnx_768") == []


def test_semantic_event_entrypoints_do_not_import_hash_bow_directly() -> None:
    """摘要：语义事件生产入口不再绕过统一 embedding provider。"""
    root = Path(__file__).resolve().parents[1]
    entrypoints = (
        root / "src/offline_companion/core/persona_session/session.py",
        root / "src/offline_companion/shell/ui_host/bootstrap.py",
        root / "src/offline_companion/shell/ui_host/desktop/http_host.py",
        root / "src/offline_companion/shell/ui_host/cli.py",
    )

    for path in entrypoints:
        source = path.read_text(encoding="utf-8")
        assert "deterministic_embedding" not in source
        assert "embed_text(" not in source
