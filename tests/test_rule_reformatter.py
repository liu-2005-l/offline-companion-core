"""摘要：B4 规则润色（Sprint 2）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from offline_companion.core.local_reformatter.rule_reformatter import (
    reformat_cloud_reply,
    should_reformat,
)
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.shared.errors import ReformatError


def _persona():
    return load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )


def test_should_reformat_short_and_english() -> None:
    p = _persona()
    assert should_reformat("OK.", p)
    assert should_reformat("This is a long English only reply for testing.", p)


def test_reformat_adds_chinese_frame_for_english() -> None:
    p = _persona()
    out = reformat_cloud_reply("This is a cold English cloud reply.", p)
    assert "整理" in out or "呢" in out or "吧" in out
    assert "cold" in out.lower() or "English" in out


def test_reformat_preserves_facts() -> None:
    p = _persona()
    out = reformat_cloud_reply("记得喝水，每天 8 杯水。", p)
    assert "8" in out
    assert "水" in out


def test_reformat_empty_raises() -> None:
    p = _persona()
    with pytest.raises(ReformatError):
        reformat_cloud_reply("   ", p)
