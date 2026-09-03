from __future__ import annotations

import importlib
import sys
from itertools import combinations
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

preexperiment = importlib.import_module("run_persona_constraint_p2_form_preexperiment2")
CORPUS_PATH = REPO_ROOT / "configs" / "persona_constraint_dimension_corpus.yaml"
LEXICON_PATH = REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml"
PATTERNS_PATH = REPO_ROOT / "configs" / "persona_constraint_l4_patterns.yaml"


def _load(path: Path) -> dict[str, object]:
    """摘要：读取 P2 语料 YAML。"""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_dimension_corpus_has_fifteen_complete_units() -> None:
    """摘要：五维三档必须各有唯一单元及两段 2–3 轮微型对话。"""
    payload = _load(CORPUS_PATH)
    units = payload["dimension_units"]
    unit_ids: list[str] = []
    scenario_families: set[str] = set()

    assert set(units) == {"O", "C", "E", "A", "N"}
    for levels in units.values():
        assert set(levels) == {"low", "mid", "high"}
        for unit in levels.values():
            unit_ids.append(unit["id"])
            assert len(unit["dialogues"]) >= 2
            for dialogue in unit["dialogues"]:
                scenario_families.add(dialogue["scenario"])
                assert 2 <= len(dialogue["turns"]) <= 3
                assert all(turn["user"] and turn["assistant"] for turn in dialogue["turns"])
    assert len(unit_ids) == len(set(unit_ids)) == 15
    assert {"joy", "frustration", "advice", "disagreement", "comfort"} <= scenario_families


def test_dimension_levels_differ_on_four_declared_features() -> None:
    """摘要：同维任两档在四项静态特征上至少存在两项差异。"""
    payload = _load(CORPUS_PATH)
    features = payload["feature_dimensions"]

    assert features == ["lexical_signature", "length_class", "punctuation_signature", "affect_signature"]
    for levels in payload["dimension_units"].values():
        for left, right in combinations(levels.values(), 2):
            differences = sum(left["signatures"][feature] != right["signatures"][feature] for feature in features)
            assert differences >= 2, (left["id"], right["id"])


def test_all_assistant_examples_pass_frozen_lexicon_and_l4_scans() -> None:
    """摘要：P2 维度语料入场前必须通过冻结禁用语义族与 L4 扫描。"""
    corpus = _load(CORPUS_PATH)
    lexicon = _load(LEXICON_PATH)
    patterns = _load(PATTERNS_PATH)

    for levels in corpus["dimension_units"].values():
        for unit in levels.values():
            for dialogue in unit["dialogues"]:
                for turn in dialogue["turns"]:
                    reply = turn["assistant"]
                    assert preexperiment.scan_forbidden(reply, lexicon) == [], (unit["id"], dialogue["id"], reply)
                    assert preexperiment.scan_l4(reply, patterns)["hit"] is False, (
                        unit["id"],
                        dialogue["id"],
                        reply,
                    )


def test_corpus_carrier_matches_branch_three_decision() -> None:
    """摘要：P2 语料只能渲染为 system 文本块，不得回流历史注入。"""
    carrier = _load(CORPUS_PATH)["carrier"]

    assert carrier["type"] == "system_embedded_dialogue_blocks"
    assert carrier["dialogue_rendering"] == "labeled_user_assistant_text"
    assert carrier["runtime_history_injection"] == "forbidden"
    assert carrier["l3_modulation"] == "primary"
