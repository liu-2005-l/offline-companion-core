from __future__ import annotations

from offline_companion.core.persona_session.session import _build_tone_instruction
from offline_companion.shared.types import OceanVector


def test_build_tone_instruction_only_uses_salient_dimensions() -> None:
    instruction = _build_tone_instruction(
        OceanVector(
            openness=0.7,
            conscientiousness=0.6,
            extraversion=0.5,
            agreeableness=0.8,
            neuroticism=0.4,
        )
    )
    assert "【语气风格】" in instruction
    assert "好奇" in instruction
    assert "温和" in instruction
    assert "有条理" not in instruction
    assert "活跃" not in instruction


def test_build_tone_instruction_returns_empty_for_midrange_profile() -> None:
    instruction = _build_tone_instruction(
        OceanVector(
            openness=0.5,
            conscientiousness=0.5,
            extraversion=0.5,
            agreeableness=0.5,
            neuroticism=0.5,
        )
    )
    assert instruction == ""
