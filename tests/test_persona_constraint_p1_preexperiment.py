from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

runner = importlib.import_module("run_persona_constraint_p1_preexperiment")
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "persona_constraints" / "p1_ea_composition.json"


def _fixture() -> dict[str, object]:
    """摘要：读取 P1 E/A 微型预实验 fixture。"""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_preexperiment_matrix_shape_is_preregistered() -> None:
    """摘要：固定四组合、三形态、四提示和双 seed 的 96 条矩阵。"""
    fixture = _fixture()
    payload = runner.run_preexperiment(fixture, lambda seed: runner._EchoBackend(), 64)

    assert len(payload["rows"]) == 96
    assert {row["profile"] for row in payload["rows"]} == {
        "E_high_A_high",
        "E_high_A_low",
        "E_low_A_high",
        "E_low_A_low",
    }
    assert set(payload["summary"]["shapes"]) == set(fixture["shapes"])


def test_system_prompt_shapes_keep_control_and_examples_separate() -> None:
    """摘要：控制组、维度拼接与结构样本提示块保持分离。"""
    fixture = _fixture()
    control = runner.build_system_prompt(fixture, "instruction_only", "high", "low")
    concatenated = runner.build_system_prompt(fixture, "dimension_concat", "high", "low")
    structural = runner.build_system_prompt(fixture, "dimension_concat_structural", "high", "low")

    assert "示例 1" not in control
    assert "【E 维微型对话】" in concatenated
    assert "【A 维微型对话】" in concatenated
    assert "【E 维微型对话】" in structural
    assert "【A 维微型对话】" in structural
    assert "【纠偏结构样本】" in structural
    assert "那就拆开看" in structural


def test_reply_scoring_uses_frozen_marker_lists() -> None:
    """摘要：评分只消费 fixture 内预注册标记，不隐藏追加实现侧词表。"""
    evaluation = _fixture()["evaluation"]
    scores = runner.score_reply("确实不容易。要不要一起说说？", evaluation)

    assert scores["extraversion_score"] == 4
    assert scores["agreeableness_score"] == 3
    assert scores["forbidden_hits"] == []
