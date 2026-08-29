from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path("src/offline_companion/shell/ui_host/desktop/static")


def test_memory_panel_loads_semantic_events_into_card_list() -> None:
    """摘要：记忆面板加载时合并 semantic_events，避免前端只显示旧 memory_chunks。"""
    source = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")

    assert "const semanticEvents = await loadSemanticEvents();" in source
    assert "const items = (semanticEvents || []).concat(data.items || []);" in source
    assert "renderMemoryCards(items);" in source
    assert "data-kind=\"' + itemKind + '\"" in source


def test_semantic_event_cards_use_real_event_endpoint_for_delete_and_edit() -> None:
    """摘要：语义事件卡片编辑和删除走 `/api/memory/events` 真实接口。"""
    source = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")

    assert "window._currentMemoryCard.dataset.kind === 'semantic_event'" in source
    assert "'/api/memory/events/' + encodeURIComponent(window._currentMemoryCard.dataset.id)" in source
    assert "'/api/memory/events/' + encodeURIComponent(id)" in source
    assert "{ method: 'DELETE' }" in source


def test_memory_panel_static_markup_has_filter_empty_and_scroll_targets() -> None:
    """摘要：记忆面板保留筛选、空状态和可滚动列表的静态挂点。"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'data-view="memory"' in html
    assert 'id="memoryCardList"' in html
    assert 'id="memoryEmptyState"' in html
    assert "filterMemoryType(this, '全部')" in html
    assert "filterMemoryType(this, '偏好')" in html
    assert "filterMemoryType(this, '事件')" in html
