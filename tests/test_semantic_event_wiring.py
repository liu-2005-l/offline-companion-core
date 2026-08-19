from __future__ import annotations

from tests.test_desktop_http import _runtime


class FakeExtractor:
    def __init__(self) -> None:
        self.calls = []
        self.last_extracted_turn = 0

    def should_extract(self, turn_count: int) -> bool:
        return turn_count == 1

    def extract(self, messages, session_id, turn_range):
        self.calls.append((messages, session_id, turn_range))
        return [object()]

    def mark_extracted(self, turn_count: int) -> None:
        self.last_extracted_turn = turn_count


def test_turn_end_triggers_semantic_extraction(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    extractor = FakeExtractor()
    runtime.orchestrator.event_extractor = extractor

    result = runtime.orchestrator.run_turn("用户决定采用本地方案", memory_on=False)

    assert result.reply
    assert len(extractor.calls) == 1
    assert extractor.calls[0][1:] == (runtime.session_id, (1, 1))
