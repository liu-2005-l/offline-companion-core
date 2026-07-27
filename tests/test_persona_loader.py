from __future__ import annotations

from pathlib import Path

import pytest

from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.shared.types import OceanVector


def test_ocean_vector_accepts_valid_range() -> None:
    ocean = OceanVector(
        openness=0.7,
        conscientiousness=0.6,
        extraversion=0.5,
        agreeableness=0.8,
        neuroticism=0.4,
    )
    assert ocean.openness == 0.7
    assert ocean.neuroticism == 0.4


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("openness", -0.1),
        ("conscientiousness", 1.1),
        ("extraversion", -0.01),
        ("agreeableness", 1.01),
        ("neuroticism", 9.9),
    ],
)
def test_ocean_vector_rejects_out_of_range(field_name: str, value: float) -> None:
    kwargs = {
        "openness": 0.5,
        "conscientiousness": 0.5,
        "extraversion": 0.5,
        "agreeableness": 0.5,
        "neuroticism": 0.5,
    }
    kwargs[field_name] = value
    with pytest.raises(ValueError):
        OceanVector(**kwargs)


def test_load_persona_file_parses_ocean(tmp_path: Path) -> None:
    persona_path = tmp_path / "ocean.yaml"
    persona_path.write_text(
        """
id: ocean-demo
name: Ocean Demo
default_companion_display_name: 助手一号
role_lock: true
memory_default_on: false
ocean:
  openness: 0.7
  conscientiousness: 0.6
  extraversion: 0.5
  agreeableness: 0.8
  neuroticism: 0.4
system_prompt: |
  你是一个温和、真诚的离线陪伴助手。
""".strip(),
        encoding="utf-8",
    )
    persona = load_persona_file(persona_path)
    assert persona.ocean is not None
    assert persona.ocean.agreeableness == 0.8


def test_load_persona_file_without_ocean_is_compatible(tmp_path: Path) -> None:
    persona_path = tmp_path / "plain.yaml"
    persona_path.write_text(
        """
id: plain
name: Plain
default_companion_display_name: 助手一号
role_lock: true
memory_default_on: false
system_prompt: |
  你是一个温和、真诚的离线陪伴助手。
""".strip(),
        encoding="utf-8",
    )
    persona = load_persona_file(persona_path)
    assert persona.ocean is None
