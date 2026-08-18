"""基于 OCR 特征集合的页面识别。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


class PageIdentifier:
    """摘要：按页面特征命中率识别当前 UI 页面。"""

    THRESHOLD = 0.6

    def __init__(self, ocr_engine: Callable[[Any], Sequence[Sequence[Any]]], *, threshold: float = THRESHOLD) -> None:
        self._ocr = ocr_engine
        self._threshold = threshold

    def identify(self, pages: list[dict[str, Any]], screenshot: Any) -> str | None:
        """摘要：返回最高命中率页面 ID，低于阈值时返回 None。"""
        current_texts = {str(item[1]) for item in self._ocr(screenshot) if len(item) >= 2}
        best_id: str | None = None
        best_ratio = 0.0
        for page in pages:
            features = {str(value) for value in page.get("features", [])}
            if not features:
                continue
            ratio = len(features & current_texts) / len(features)
            if ratio >= self._threshold and ratio > best_ratio:
                best_id = str(page.get("id"))
                best_ratio = ratio
        return best_id
