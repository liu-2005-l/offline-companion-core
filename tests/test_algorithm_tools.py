from __future__ import annotations

import pytest

from offline_companion.core.algorithm_tools import booth_multiply, format_booth_result


def test_booth_multiply_returns_deterministic_trace() -> None:
    trace = booth_multiply(7, 3)

    assert trace["algorithm"] == "booth"
    assert trace["result"] == 21
    assert trace["recoding"] == "3 = +4 -1"
    assert trace["partial_products"] == [28, -7]
    assert len(trace["rounds"]) == trace["bit_width"]
    assert trace["rounds"][0]["pair"] == "10"
    assert trace["rounds"][2]["pair"] == "01"
    rendered = format_booth_result(trace)
    assert "乘数重编码：3 = +4 -1" in rendered
    assert "部分积：28 - 7 = 21" in rendered
    assert "A = A - M" in rendered
    assert "A = A + M" in rendered
    assert "= 21" in rendered


@pytest.mark.parametrize(
    ("multiplicand", "multiplier"),
    [(0, 7), (7, 0), (3, 5), (-7, 3), (7, -3), (-7, -3)],
)
def test_booth_multiply_matches_integer_arithmetic(multiplicand: int, multiplier: int) -> None:
    assert booth_multiply(multiplicand, multiplier)["result"] == multiplicand * multiplier


def test_booth_multiply_rejects_boolean_operands() -> None:
    with pytest.raises(TypeError):
        booth_multiply(True, 3)
