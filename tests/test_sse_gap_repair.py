"""SSE seq 缺口修复的静态行为约束。"""

from pathlib import Path

SHELL_API = (
    Path(__file__).resolve().parents[1]
    / "src/offline_companion/shell/ui_host/desktop/static/shell_api.js"
)


def test_sse_reader_detects_gap_and_repairs_before_processing_frame() -> None:
    source = SHELL_API.read_text(encoding="utf-8")

    assert "eventSeq <= latestSeq" in source
    assert "seq > latestSeq + 1" in source
    assert "options.onGap(latestSeq, seq - 1)" in source
    assert "SSE 事件缺口修复失败" in source


def test_sse_reconnect_reuses_last_sequence_and_deduplicates_history() -> None:
    source = SHELL_API.read_text(encoding="utf-8")

    assert "let lastStreamSeq = await apiLatestSseSeq(_currentSessionId);" in source
    assert "Number.MAX_SAFE_INTEGER" in source
    assert "initialSeq: lastStreamSeq" in source
    assert "onGap: repairGap" in source
    assert "eventSeq <= latestSeq" in source
    assert "apiRepairSseGap(_currentSessionId, fromSeq, handleStreamEvent, untilSeq)" in source


def test_sse_gap_repair_stops_when_no_progress_is_possible() -> None:
    source = SHELL_API.read_text(encoding="utf-8")

    assert "let progressed = false" in source
    assert "eventSeq > upperBound" in source
    assert "if (!progressed && (data.events || []).length > 0) break;" in source
