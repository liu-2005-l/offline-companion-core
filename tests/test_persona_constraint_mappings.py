from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = REPO_ROOT / "configs" / "persona_constraint_mappings.yaml"


def _load_mapping() -> dict[str, object]:
    """摘要：读取 P1 人格约束映射定义。"""
    payload = yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_ocean_dimension_order_and_storage_domains_are_frozen() -> None:
    """摘要：固定 OCEAN 位置语义，并区分 DB 数组与 YAML 映射边界。"""
    payload = _load_mapping()
    ocean = payload["ocean"]

    assert ocean["dimension_order"] == ["O", "C", "E", "A", "N"]
    assert ocean["dimensions"] == {
        "O": "openness",
        "C": "conscientiousness",
        "E": "extraversion",
        "A": "agreeableness",
        "N": "neuroticism",
    }
    assert ocean["storage_domains"]["database_api_ui"] == {
        "type": "integer_array",
        "minimum": 0,
        "maximum": 100,
    }
    assert ocean["storage_domains"]["yaml"] == {
        "type": "named_number_mapping",
        "minimum": 0.0,
        "maximum": 1.0,
    }


def test_ocean_level_cuts_cover_every_integer_without_overlap() -> None:
    """摘要：钉住 low/mid/high 初始切点及 33/34、66/67 边界归属。"""
    levels = _load_mapping()["ocean"]["levels"]
    assigned: dict[int, str] = {}
    for level_name, bounds in levels.items():
        for value in range(bounds["minimum"], bounds["maximum"] + 1):
            assert value not in assigned
            assigned[value] = level_name

    assert assigned == {
        value: "low" if value <= 33 else "mid" if value <= 66 else "high" for value in range(101)
    }
    assert [assigned[value] for value in (33, 34, 66, 67)] == ["low", "mid", "mid", "high"]


def test_trait_mapping_is_complete_and_style_traits_keep_c_mid() -> None:
    """摘要：验证五个人格标定点完整，且风格型人格不通过 C 维交换任务质量。"""
    payload = _load_mapping()
    dimensions = set(payload["ocean"]["dimension_order"])
    traits = payload["traits"]

    assert list(traits) == ["温柔", "暴躁", "可靠", "甜美", "可爱"]
    assert {entry["type"] for entry in traits.values()} == {"style", "behavior"}
    for entry in traits.values():
        assert set(entry["levels"]) == dimensions
        assert set(entry["levels"].values()) <= {"low", "mid", "high"}
    for entry in traits.values():
        if entry["type"] == "style":
            assert entry["levels"]["C"] == "mid"

    assert traits["可靠"]["levels"]["C"] == "high"
