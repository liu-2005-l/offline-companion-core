import json
from decimal import Decimal

import pytest

from offline_companion.core.calculator import calculate_expression, parse_calculation_request
from offline_companion.core.tools.calculator_tool import calculator_tool


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("计算三乘七", {"left": "三", "operator": "乘", "right": "七"}),
        ("请算一下 12 除以 3", {"left": "12", "operator": "除以", "right": "3"}),
    ],
)
def test_parse_calculation_request(text: str, expected: dict[str, str]) -> None:
    assert parse_calculation_request(text) == expected


def test_calculate_chinese_multiplication_is_deterministic() -> None:
    result = calculate_expression("三", "乘", "七")

    assert result["result"] == Decimal(21)
    assert result["formatted"] == "3 乘 7 = 21"


def test_calculate_division_by_zero_is_rejected() -> None:
    with pytest.raises(ZeroDivisionError):
        calculate_expression(7, "除以", 0)


def test_calculator_tool_returns_json_safe_values() -> None:
    result = calculator_tool("三", "乘", "七")

    assert result["result"] == "21"
    assert all(not isinstance(value, Decimal) for value in result.values())
    json.dumps(result, ensure_ascii=False)
