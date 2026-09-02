from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml"
REDLINE_PATH = REPO_ROOT / "fixtures" / "persona_constraints" / "p1_redline_cases.json"


def _load_lexicon() -> dict[str, object]:
    """摘要：读取 P1 人格词表。"""
    payload = yaml.safe_load(LEXICON_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _load_redlines() -> dict[str, object]:
    """摘要：读取 P1 红线及对抗性判例。"""
    payload = json.loads(REDLINE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_trait_lexicon_separates_style_and_reliable_behavior() -> None:
    """摘要：四个风格人格使用表达词表，可靠人格只定义行为证据。"""
    traits = _load_lexicon()["traits"]

    assert list(traits) == ["温柔", "暴躁", "可靠", "甜美", "可爱"]
    for trait_name, trait in traits.items():
        assert len(trait["disagreement_examples"]) >= 2
        assert len(trait["low_intensity_comfort"]) >= 2
        assert len(trait["avoid"]) >= 4
        if trait_name == "可靠":
            assert trait["type"] == "behavior"
            assert "behavior_cues" in trait
            assert "expression_cues" not in trait
        else:
            assert trait["type"] == "style"
            assert len(trait["expression_cues"]) >= 4


def test_forbidden_markers_are_grouped_by_semantic_family() -> None:
    """摘要：禁用标记按语义族组织，并覆盖身份措辞变体。"""
    payload = _load_lexicon()
    families = payload["forbidden_semantic_families"]

    assert payload["gate_policy"]["forbidden_marker_gate"] != payload["gate_policy"]["naturalness_gate"]
    assert payload["gate_policy"]["gates_must_remain_independent"] is True
    assert set(families["base_identity_leak"]["variants"]) >= {
        "作为一个AI",
        "作为AI助手",
        "作为 AI 助手",
        "我是AI",
        "我是一个AI助手",
    }
    all_variants = [variant for family in families.values() for variant in family["variants"]]
    assert len(all_variants) == len(set(all_variants))
    for family in families.values():
        assert family["core_semantics"]
        assert family["normalization"]
        assert len(family["variants"]) >= 4


def test_redline_fixture_covers_five_lines_and_disagreement_risk() -> None:
    """摘要：五条红线等量覆盖，且分歧类与对抗性判例具有预注册密度。"""
    payload = _load_redlines()
    cases = payload["cases"]
    counts = Counter(case["redline"] for case in cases)

    assert len(cases) == 20
    assert counts == {"audit": 4, "honesty": 4, "task": 4, "user": 4, "intelligence": 4}
    assert len({case["id"] for case in cases}) == len(cases)
    assert sum("disagreement" in case["challenge_tags"] for case in cases) >= 7
    for redline in counts:
        assert any(case["redline"] == redline and "adversarial" in case["challenge_tags"] for case in cases)


def test_redline_fixture_reuses_frozen_baselines_and_keeps_gates_independent() -> None:
    """摘要：复用既有诚实与任务基线，且自然度不与模式命中合并。"""
    payload = _load_redlines()
    baseline_assets = payload["baseline_assets"]

    assert baseline_assets["honesty_case_ids"] == ["S07", "S09", "M08"]
    assert baseline_assets["task_case_ids"] == [f"T{index:02d}" for index in range(1, 13)]
    for relative_path in baseline_assets["audit_test_files"]:
        assert (REPO_ROOT / relative_path).is_file()
    assert payload["gate_policy"]["forbidden_marker_gate"] != payload["gate_policy"]["naturalness_gate"]
