from __future__ import annotations

from scripts.gbnf_experiment import (
    BoothCase,
    booth_steps_grammar,
    build_report,
    select_cases,
    validate_booth_output,
)

from offline_companion.core.algorithm_tools import booth_multiply


def test_select_cases_defaults_to_distribution() -> None:
    """摘要：默认实验集覆盖 20 个不同乘法对。"""
    cases = select_cases("distribution", 20)

    assert len(cases) == 20
    assert len({(case.multiplicand, case.multiplier) for case in cases}) == 20
    assert cases[0].prompt.startswith("请严格按 Booth 乘法算法计算")


def test_select_cases_repeat_mode_uses_stability_probe() -> None:
    """摘要：repeat 模式用于同一输入的采样稳定性探针。"""
    cases = select_cases("repeat", 3)

    assert [(case.multiplicand, case.multiplier) for case in cases] == [(7, 3)] * 3


def test_booth_steps_grammar_constrains_required_fields() -> None:
    """摘要：Booth 文法固定输出字段与轮次字段。"""
    grammar = booth_steps_grammar()

    assert '"\\"multiplicand\\":" ws integer' in grammar
    assert '"\\"rounds\\":" ws round-array' in grammar
    assert '"\\"pair\\":" ws pair' in grammar


def test_validate_booth_output_requires_full_trace() -> None:
    """摘要：全成功要求结果、重编码、部分积和轮次全部对齐。"""
    case = BoothCase("demo", 7, 3)
    expected = booth_multiply(7, 3)
    output = {
        "multiplicand": 7,
        "multiplier": 3,
        "recoding": expected["recoding"],
        "partial_products": expected["partial_products"],
        "rounds": [
            {
                "round": item["round"],
                "pair": item["pair"],
                "accumulator_after_shift": item["accumulator_after_shift"],
                "multiplier_after_shift": item["multiplier_after_shift"],
            }
            for item in expected["rounds"]
        ],
        "result": 21,
    }

    assert validate_booth_output(case, output)["full_success"] is True
    output["result"] = 14
    validation = validate_booth_output(case, output)
    assert validation["result"] is False
    assert validation["full_success"] is False


def test_build_report_marks_preflight_blocked_as_blocked() -> None:
    """摘要：sidecar 不在线时实验只记录 blocked，不产生路线判决。"""
    protocol = {
        "experiment": "booth_gbnf_plan_as_reasoning",
        "case_set": "distribution",
        "samples": 1,
        "temperature": 0.7,
        "seed": 1,
        "decision_metric": "full_success_rate",
        "diagnostic_metrics": (),
    }
    result = {
        "status": "blocked",
        "validation": {
            "input": False,
            "result": False,
            "recoding": False,
            "partial_products": False,
            "rounds": False,
            "full_success": False,
        },
    }

    report = build_report(protocol, {"status": "blocked"}, [result])

    assert report["status"] == "blocked"
    assert report["completed"] == 0
    assert report["metrics"]["full_success_rate"] == 0.0
