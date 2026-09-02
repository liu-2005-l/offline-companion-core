from __future__ import annotations

import importlib
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

calculate_metrics = importlib.import_module("persona_expression_metrics").calculate_metrics
run_baseline = importlib.import_module("run_persona_expression_w1_baseline").run_baseline
run_b1 = importlib.import_module("run_persona_expression_w1_b1").run_b1
exclusive_w2_run_lock = importlib.import_module("run_persona_expression_w2")._exclusive_run_lock


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "persona_expression"


def test_w1_fixtures_keep_preregistered_counts() -> None:
    cases = json.loads((FIXTURE_DIR / "w1_cases.json").read_text(encoding="utf-8"))
    probe = json.loads((FIXTURE_DIR / "w1_probe_turns.json").read_text(encoding="utf-8"))

    case_turns = sum(len(case["turns"]) for case in cases["cases"])
    scenario_counts: dict[str, int] = {}
    for case in cases["cases"]:
        scenario_counts[case["scenario"]] = scenario_counts.get(case["scenario"], 0) + len(case["turns"])

    assert len(cases["cases"]) == 37
    assert case_turns == 40
    assert scenario_counts == {"chat": 18, "technical": 12, "memory": 10}
    assert len(cases["memory_bundle"]) == 6
    assert len(probe["turns"]) == 50
    assert probe["seeds"] == [42, 1337]
    assert [turn["turn"] for turn in probe["turns"] if turn["is_probe"]] == [10, 20, 30, 40, 50]
    assert cases["cases"][0]["turns"][0]["user"].startswith("今天没什么事")


def test_persona_expression_metrics_on_synthetic_replies() -> None:
    payload = {
        "cases": [
            {
                "id": "Sx",
                "scenario": "chat",
                "group": "Sx",
                "replies": ["你好啊。其实可以先休息一下呢。"],
            },
            {
                "id": "Mx",
                "scenario": "memory",
                "group": "Mx",
                "replies": ["首先，记得你喜欢水煮鱼。\n- 可以吃辣一点。"],
            },
            {
                "id": "Tx",
                "scenario": "technical",
                "group": "Tx",
                "replies": ["1. 这是技术列表，不纳入六指标。"],
            },
        ]
    }

    metrics = calculate_metrics(payload)

    assert metrics["aggregate"]["style_case_count"] == 2
    assert metrics["aggregate"]["list_dependency_rate"] == 0.5
    assert metrics["per_case"]["Sx"]["colloquial_marker_hits"] >= 2
    assert "Tx" not in metrics["per_case"]


def test_w1_baseline_runner_echo_schema(tmp_path) -> None:
    args = Namespace(
        cases=FIXTURE_DIR / "w1_cases.json",
        probe=FIXTURE_DIR / "w1_probe_turns.json",
        persona=Path("configs/personas/default.yaml"),
        backend="echo",
        model=None,
        max_tokens=64,
        n_ctx=512,
        n_gpu_layers=0,
        skip_health_check=True,
        verbose=False,
    )

    payload = run_baseline(args)

    assert payload["meta"]["model"] == "echo"
    assert len(payload["cases"]) == 37
    assert sum(len(case["replies"]) for case in payload["cases"]) == 40
    assert sorted(payload["probe"]) == ["seed1337", "seed42"]
    assert len(payload["probe"]["seed42"]["replies"]) == 50
    assert payload["metrics"]["aggregate"]["style_case_count"] == 25
    assert any(
        count > 0
        for case in payload["cases"]
        if case["scenario"] == "memory"
        for count in case["recall_counts"]
    )


def test_w1_b1_runner_echo_schema(tmp_path) -> None:
    cases_path = tmp_path / "cases.json"
    probe_path = tmp_path / "probe.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": "test",
                "memory_bundle": [{"id": "MF3", "content": "事件：下周三有操作系统期末考试"}],
                "cases": [
                    {
                        "id": "M01",
                        "scenario": "memory",
                        "group": "M01",
                        "turns": [{"user": "我下周三要考什么来着？"}],
                        "focus": ["memory_weaving"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    probe_path.write_text(
        json.dumps(
            {
                "version": "test",
                "seeds": [42],
                "probe_points": [1],
                "turns": [
                    {
                        "turn": 1,
                        "domain": "identity_probe",
                        "user": "你现在叫什么名字来着？",
                        "is_probe": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args = Namespace(
        cases=cases_path,
        probe=probe_path,
        persona=Path("configs/personas/default.yaml"),
        backend="echo",
        model=None,
        output=tmp_path / "out.json",
        max_tokens=64,
        n_ctx=512,
        n_gpu_layers=0,
        skip_health_check=True,
        verbose=False,
        case_seeds=(42,),
        probe_seeds=(42,),
        verify_seed=42,
        include_paired_probe=False,
        allow_nondeterministic=False,
        skip_seed_control=False,
        skip_cases=False,
        skip_probe=False,
    )

    payload = run_b1(args)

    assert payload["seed_control"]["byte_identical"] is True
    assert payload["seed_control"]["compared_reply_count"] == 2
    assert sorted(payload["case_runs"]) == ["seed42"]
    assert payload["probe_summary"]["run_count"] == 1


def test_w2_matrix_lock_rejects_parallel_runner(tmp_path) -> None:
    """摘要：同一锁文件只能有一个 W2 矩阵进程，防止并行采样污染。"""
    lock_path = tmp_path / "w2_matrix.lock"

    with (
        exclusive_w2_run_lock(lock_path),
        pytest.raises(RuntimeError, match="已有 W2 矩阵进程"),
        exclusive_w2_run_lock(lock_path),
    ):
        pass
