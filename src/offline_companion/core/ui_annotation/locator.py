"""基于 OCR 的 UI 元素定位与像素坐标缓存。"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

OCRResult = Sequence[Any]
OcrEngine = Callable[[Any], Sequence[OCRResult]]


@dataclass(frozen=True)
class LocateResult:
    """摘要：一次 UI 元素定位结果。"""

    found: bool
    x: int = 0
    y: int = 0
    error: str | None = None


@dataclass
class LocatorCache:
    """摘要：缓存 OCR 得到的实际像素中心点。"""

    x: int
    y: int
    region: tuple[float, float, float, float]
    timestamp: float

    def is_expired(self, ttl: float) -> bool:
        """摘要：判断缓存是否超过 TTL。"""
        return time.monotonic() - self.timestamp >= ttl


class PageLocator:
    """摘要：在百分比区域内定位 OCR 文本，并提供轻量缓存复核。

    参数：
        ocr_engine: 接收截图并返回 ``[box, text, score]`` 项的 OCR 函数。
        capture_screen: 无参数截图回调；返回截图对象或 ``(截图, (宽, 高))``。
        capture_crop: 可选的局部截图回调，参数为 ``x, y, size``。
        screen_size: 截图未携带尺寸时使用的宽高。
    """

    def __init__(
        self,
        ocr_engine: OcrEngine,
        *,
        capture_screen: Callable[[], Any] | None = None,
        capture_crop: Callable[[int, int, int], Any] | None = None,
        screen_size: tuple[int, int] = (100, 100),
        cache_ttl: float = 10.0,
    ) -> None:
        self._ocr = ocr_engine
        self._capture_screen_callback = capture_screen
        self._capture_crop_callback = capture_crop
        self._screen_size = screen_size
        self._cache_ttl = max(0.0, cache_ttl)
        self._cache: dict[str, LocatorCache] = {}

    def locate(self, target_text: str, region: list[float], screenshot: Any | None = None) -> LocateResult:
        """摘要：先复核缓存，失败后执行全屏 OCR 定位。"""
        normalized = self._normalize_region(region)
        cache_key = f"{target_text}:{normalized}"
        cached = self._cache.get(cache_key)
        if cached is not None and not cached.is_expired(self._cache_ttl):
            verified = self._verify_cache(cached, target_text)
            if verified is not None:
                return verified
        return self._locate_full(target_text, normalized, screenshot, cache_key)

    def invalidate(self, target_text: str | None = None) -> None:
        """摘要：清除一个元素缓存或清空全部缓存。"""
        if target_text is None:
            self._cache.clear()
            return
        for key in tuple(self._cache):
            if key.startswith(f"{target_text}:"):
                self._cache.pop(key, None)

    def _locate_full(
        self,
        target_text: str,
        region: tuple[float, float, float, float],
        screenshot: Any | None,
        cache_key: str,
    ) -> LocateResult:
        image, size = self._screen(screenshot)
        for item in self._ocr(image):
            match = self._match(item, target_text, region, size)
            if match is None:
                continue
            x, y = match
            self._cache[cache_key] = LocatorCache(x, y, region, time.monotonic())
            return LocateResult(found=True, x=x, y=y)
        self._cache.pop(cache_key, None)
        return LocateResult(found=False, error="E_UI_ELEMENT_NOT_FOUND")

    def _verify_cache(self, cached: LocatorCache, target_text: str) -> LocateResult | None:
        if self._capture_crop_callback is None:
            return LocateResult(found=True, x=cached.x, y=cached.y)
        crop = self._capture_crop_callback(cached.x, cached.y, 100)
        for item in self._ocr(crop):
            if str(item[1]) != target_text:
                continue
            box = item[0]
            center_x = sum(float(point[0]) for point in box) / len(box)
            center_y = sum(float(point[1]) for point in box) / len(box)
            if abs(center_x - 50) <= 15 and abs(center_y - 50) <= 15:
                return LocateResult(found=True, x=cached.x, y=cached.y)
        self._cache.pop(f"{target_text}:{cached.region}", None)
        return None

    def _screen(self, screenshot: Any | None) -> tuple[Any, tuple[int, int]]:
        image = screenshot
        if image is None:
            if self._capture_screen_callback is None:
                raise RuntimeError("未配置截图回调")
            image = self._capture_screen_callback()
        if isinstance(image, tuple) and len(image) == 2 and isinstance(image[1], tuple):
            return image[0], image[1]
        return image, self._screen_size

    @staticmethod
    def _normalize_region(region: list[float]) -> tuple[float, float, float, float]:
        if len(region) != 4:
            raise ValueError("region 必须包含四个百分比")
        values = tuple(float(value) for value in region)
        if not (0 <= values[0] < values[2] <= 100 and 0 <= values[1] < values[3] <= 100):
            raise ValueError("region 必须是有效的百分比矩形")
        return values

    @staticmethod
    def _match(item: OCRResult, target_text: str, region: tuple[float, float, float, float], size: tuple[int, int]) -> tuple[int, int] | None:
        if len(item) < 2 or str(item[1]) != target_text:
            return None
        box = item[0]
        width, height = size
        center_x = sum(float(point[0]) for point in box) / len(box)
        center_y = sum(float(point[1]) for point in box) / len(box)
        x_percent = center_x / width * 100
        y_percent = center_y / height * 100
        if region[0] <= x_percent <= region[2] and region[1] <= y_percent <= region[3]:
            return round(center_x), round(center_y)
        return None
