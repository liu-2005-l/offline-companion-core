"""semantic_embedding_provider：语义事件 embedding 的统一生产入口。"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from offline_companion.shared.deterministic_embedding import embed_text
from offline_companion.shared.runtime_paths import models_dir

from .event_types import CONTENT_EMBEDDING_DIMENSIONS

try:
    import onnxruntime as ort
except ImportError:  # pragma: no cover
    ort = None

try:
    from tokenizers import Tokenizer
except ImportError:  # pragma: no cover
    Tokenizer = None

logger = logging.getLogger(__name__)
_FALLBACK_WARNING_EMITTED = False
HASH_BOW_EMBEDDING_SPACE = "hash_bow_768"
SEMANTIC_ONNX_EMBEDDING_SPACE = "semantic_onnx_768"
NO_EMBEDDING_SPACE = "none"


@dataclass(frozen=True)
class SemanticEmbeddingModelPaths:
    """摘要：描述本地 semantic embedding 模型与 tokenizer 的文件位置。"""

    model_path: Path
    tokenizer_path: Path


class SemanticEmbeddingProvider:
    """摘要：优先使用本地 ONNX embedding，缺失时回退 deterministic hash-bow。

    参数：
        data_root: 可选的数据根目录，用于解析用户模型目录。
        model_paths: 显式模型路径，测试或手工配置时使用。
        dimensions: 输出向量维度，语义事件当前固定为 768。
        fallback: ONNX 不可用时的降级 embedding 函数。
    """

    def __init__(
        self,
        *,
        data_root: Path | None = None,
        model_paths: SemanticEmbeddingModelPaths | None = None,
        dimensions: int = CONTENT_EMBEDDING_DIMENSIONS,
        fallback: Callable[[str], list[float]] | None = None,
    ) -> None:
        self._dimensions = dimensions
        self._fallback = fallback or (
            lambda text: embed_text(text, dimensions=self._dimensions)
        )
        self._model_paths = model_paths or discover_semantic_embedding_model(data_root=data_root)
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._last_space = HASH_BOW_EMBEDDING_SPACE

    def __call__(self, text: str) -> list[float]:
        """摘要：返回 L2 归一化的语义事件向量。"""
        try:
            vector = self._embed_with_onnx(text)
            self._last_space = SEMANTIC_ONNX_EMBEDDING_SPACE
            return vector
        except (OSError, RuntimeError, TypeError, ValueError):
            _warn_fallback_once()
            vector = self._fallback(text)
            self._last_space = HASH_BOW_EMBEDDING_SPACE
            return vector

    @property
    def embedding_space(self) -> str:
        """摘要：返回最近一次成功生成向量所属的语义空间。"""
        return self._last_space

    @property
    def preferred_embedding_space(self) -> str:
        """摘要：返回当前启动状态下期望写满全库的向量空间。"""
        return (
            SEMANTIC_ONNX_EMBEDDING_SPACE
            if self.using_model
            else HASH_BOW_EMBEDDING_SPACE
        )

    @property
    def using_model(self) -> bool:
        """摘要：返回当前 provider 是否具备可加载的 ONNX 模型文件。"""
        return (
            ort is not None
            and Tokenizer is not None
            and self._model_paths is not None
            and self._model_paths.model_path.is_file()
            and self._model_paths.tokenizer_path.is_file()
        )

    def _embed_with_onnx(self, text: str) -> list[float]:
        if not self.using_model or self._model_paths is None:
            raise RuntimeError("semantic embedding model is unavailable")
        session = self._load_session()
        tokenizer = self._load_tokenizer()
        encoded = tokenizer.encode(text or "")
        input_ids = encoded.ids or [0]
        attention_mask = encoded.attention_mask or [1] * len(input_ids)

        import numpy as np

        inputs = session.get_inputs()
        if not inputs:
            raise RuntimeError("semantic embedding model has no inputs")
        feeds: dict[str, Any] = {inputs[0].name: np.array([input_ids], dtype=np.int64)}
        if len(inputs) >= 2:
            feeds[inputs[1].name] = np.array([attention_mask], dtype=np.int64)
        outputs = session.run(None, feeds)
        if not outputs:
            raise RuntimeError("semantic embedding model returned no outputs")
        values = _flatten_embedding_output(outputs[0], attention_mask)
        normalized = _normalize(values)
        if len(normalized) != self._dimensions:
            raise ValueError(
                f"semantic embedding must have {self._dimensions} dimensions"
            )
        return normalized

    def _load_session(self) -> Any:
        if self._session is None:
            if ort is None or self._model_paths is None:
                raise RuntimeError("onnxruntime is unavailable")
            self._session = ort.InferenceSession(
                str(self._model_paths.model_path),
                providers=["CPUExecutionProvider"],
            )
        return self._session

    def _load_tokenizer(self) -> Any:
        if self._tokenizer is None:
            if Tokenizer is None or self._model_paths is None:
                raise RuntimeError("tokenizers is unavailable")
            self._tokenizer = Tokenizer.from_file(str(self._model_paths.tokenizer_path))
        return self._tokenizer


def discover_semantic_embedding_model(
    *, data_root: Path | None = None
) -> SemanticEmbeddingModelPaths | None:
    """摘要：在模型目录中发现约定的 semantic embedding ONNX 文件。"""
    root = models_dir(data_root_override=data_root)
    candidates = (
        (
            root / "semantic-embedding" / "model.onnx",
            root / "semantic-embedding" / "tokenizer.json",
        ),
        (
            root / "bge-base-zh-v1.5" / "model.onnx",
            root / "bge-base-zh-v1.5" / "tokenizer.json",
        ),
        (
            root / "semantic_embedding.onnx",
            root / "semantic_embedding_tokenizer.json",
        ),
    )
    for model_path, tokenizer_path in candidates:
        if model_path.is_file() and tokenizer_path.is_file():
            return SemanticEmbeddingModelPaths(model_path, tokenizer_path)
    return None


def reset_semantic_embedding_fallback_warning() -> None:
    """摘要：重置降级 warning 哨兵，供测试隔离使用。"""
    global _FALLBACK_WARNING_EMITTED
    _FALLBACK_WARNING_EMITTED = False


def embedding_space_of(embedding_func: Callable[[str], list[float]]) -> str:
    """摘要：读取 embedding callable 最近一次输出所属空间。"""
    value = getattr(embedding_func, "embedding_space", HASH_BOW_EMBEDDING_SPACE)
    return str(value or HASH_BOW_EMBEDDING_SPACE)


def preferred_embedding_space_of(embedding_func: Callable[[str], list[float]]) -> str:
    """摘要：读取 embedding callable 当前期望的全库目标空间。"""
    value = getattr(
        embedding_func,
        "preferred_embedding_space",
        HASH_BOW_EMBEDDING_SPACE,
    )
    return str(value or HASH_BOW_EMBEDDING_SPACE)


def _warn_fallback_once() -> None:
    global _FALLBACK_WARNING_EMITTED
    if _FALLBACK_WARNING_EMITTED:
        return
    _FALLBACK_WARNING_EMITTED = True
    logger.warning("semantic embedding model unavailable; falling back to hash-bow")


def _flatten_embedding_output(output: Any, attention_mask: list[int]) -> list[float]:
    array = getattr(output, "tolist", lambda: output)()
    if not isinstance(array, list) or not array:
        raise RuntimeError("semantic embedding output is empty")
    first = array[0]
    if isinstance(first, list) and first and isinstance(first[0], list):
        token_vectors = first
        active = [index for index, value in enumerate(attention_mask) if value]
        if not active:
            active = list(range(len(token_vectors)))
        width = len(token_vectors[0])
        pooled = [0.0] * width
        count = 0
        for index in active:
            if index >= len(token_vectors):
                continue
            vector = token_vectors[index]
            if len(vector) != width:
                raise ValueError("semantic embedding token vector width mismatch")
            pooled = [left + float(right) for left, right in zip(pooled, vector, strict=True)]
            count += 1
        if count <= 0:
            raise RuntimeError("semantic embedding has no active tokens")
        return [value / count for value in pooled]
    if isinstance(first, list):
        return [float(value) for value in first]
    return [float(value) for value in array]


def _normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        raise ValueError("semantic embedding output is zero vector")
    return [value / norm for value in values]
