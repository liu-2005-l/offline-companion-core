"""PageLocator 与 PageIdentifier 回归测试。"""

from __future__ import annotations

from offline_companion.core.ui_annotation import PageIdentifier, PageLocator


def test_locator_uses_region_to_select_unique_match() -> None:
    calls = []

    def ocr(_image):
        calls.append("ocr")
        return [([[10, 10], [20, 10], [20, 20], [10, 20]], "发送", 0.99), ([[80, 80], [90, 80], [90, 90], [80, 90]], "发送", 0.99)]

    locator = PageLocator(ocr, screen_size=(100, 100), capture_screen=lambda: "screen")
    result = locator.locate("发送", [70, 70, 100, 100])
    assert (result.found, result.x, result.y) == (True, 85, 85)
    assert calls == ["ocr"]


def test_locator_cache_crop_verification_avoids_full_scan() -> None:
    calls = []

    def ocr(image):
        calls.append(image)
        if image == "crop":
            return [([[40, 40], [60, 40], [60, 60], [40, 60]], "发送", 0.99)]
        return [([[80, 80], [90, 80], [90, 90], [80, 90]], "发送", 0.99)]

    locator = PageLocator(
        ocr,
        screen_size=(100, 100),
        capture_screen=lambda: "screen",
        capture_crop=lambda _x, _y, _size: "crop",
    )
    assert locator.locate("发送", [70, 70, 100, 100]).found
    assert locator.locate("发送", [70, 70, 100, 100]).found
    assert calls == ["screen", "crop"]


def test_locator_cache_failure_relocates() -> None:
    state = {"crop_valid": True}

    def ocr(image):
        if image == "crop" and not state["crop_valid"]:
            return []
        return [([[80, 80], [90, 80], [90, 90], [80, 90]], "发送", 0.99)]

    locator = PageLocator(ocr, screen_size=(100, 100), capture_screen=lambda: "screen", capture_crop=lambda *_: "crop")
    locator.locate("发送", [70, 70, 100, 100])
    state["crop_valid"] = False
    assert locator.locate("发送", [70, 70, 100, 100]).found


def test_page_identifier_requires_sixty_percent() -> None:
    ocr = lambda _image: [([[0, 0]], text, 1.0) for text in ("微信", "发送", "文件")]
    identifier = PageIdentifier(ocr)
    pages = [{"id": "chat", "features": ["微信", "发送", "文件"]}, {"id": "main", "features": ["微信", "通讯录"]}]
    assert identifier.identify(pages, "screen") == "chat"
    assert identifier.identify([{"id": "main", "features": ["微信", "通讯录", "设置"]}], "screen") is None
