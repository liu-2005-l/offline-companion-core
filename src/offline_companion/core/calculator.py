"""calculator：解析并执行可机械验证的基础算术表达式。"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

_NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百千万亿]+)"
_EXPRESSION = re.compile(
    rf"(?P<left>{_NUMBER})\s*(?P<operator>乘以|除以|乘|加|减|\+|-|\*|/|÷|×|\^|\*\*)\s*"
    rf"(?P<right>{_NUMBER})"
)
_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10_000, "亿": 100_000_000}
_OPERATORS = {
    "乘以": "multiply",
    "乘": "multiply",
    "*": "multiply",
    "×": "multiply",
    "加": "add",
    "+": "add",
    "减": "subtract",
    "-": "subtract",
    "除以": "divide",
    "/": "divide",
    "÷": "divide",
    "^": "power",
    "**": "power",
}


def calculate_expression(left: str | int, operator: str, right: str | int) -> dict[str, Any]:
    """摘要：确定性执行两个操作数的基础算术。

    参数：
        left: 左操作数，可为阿拉伯数字或中文数字。
        operator: 运算符。
        right: 右操作数，可为阿拉伯数字或中文数字。

    返回值：
        包含规范表达式、结果和审计信息的字典。
    """
    left_value = _to_decimal(left)
    right_value = _to_decimal(right)
    normalized_operator = _OPERATORS.get(operator, operator)
    with localcontext() as context:
        context.prec = 64
        if normalized_operator == "add":
            result = left_value + right_value
        elif normalized_operator == "subtract":
            result = left_value - right_value
        elif normalized_operator == "multiply":
            result = left_value * right_value
        elif normalized_operator == "divide":
            if right_value == 0:
                raise ZeroDivisionError("calculator division by zero")
            result = left_value / right_value
        elif normalized_operator == "power":
            if right_value != right_value.to_integral_value() or abs(right_value) > 1000:
                raise ValueError("calculator power exponent must be an integer within 1000")
            result = left_value ** int(right_value)
        else:
            raise ValueError(f"unsupported calculator operator: {operator}")
    expression = f"{_format_decimal(left_value)} {operator} {_format_decimal(right_value)}"
    return {
        "expression": expression,
        "left": left_value,
        "operator": normalized_operator,
        "right": right_value,
        "result": result,
        "formatted": f"{expression} = {_format_decimal(result)}",
    }


def parse_calculation_request(text: str) -> dict[str, str] | None:
    """摘要：从用户输入中提取一个基础算术表达式。"""
    match = _EXPRESSION.search(str(text or ""))
    if match is None:
        return None
    return {
        "left": match.group("left"),
        "operator": match.group("operator"),
        "right": match.group("right"),
    }


def parse_integer(value: str | int) -> int:
    """摘要：解析一个整数操作数，供确定性算法路由复用。"""
    number = _to_decimal(value)
    if number != number.to_integral_value():
        raise ValueError(f"expected integer operand: {value}")
    return int(number)


def _to_decimal(value: str | int) -> Decimal:
    text = str(value).strip()
    if text and all(char in _DIGITS or char in _UNITS for char in text.lstrip("+-")):
        sign = -1 if text.startswith("-") else 1
        text = text.lstrip("+-")
        return Decimal(sign * _parse_chinese_number(text))
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid calculator operand: {value}") from exc


def _parse_chinese_number(text: str) -> int:
    total = 0
    section = 0
    digit = 0
    for char in text:
        if char in _DIGITS:
            digit = _DIGITS[char]
        elif char in _UNITS:
            unit = _UNITS[char]
            if unit < 10_000:
                section += (digit or 1) * unit
            else:
                total += (section + digit) * unit
                section = 0
            digit = 0
        else:
            raise ValueError(f"invalid Chinese number: {text}")
    return total + section + digit


def _format_decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(value.quantize(Decimal(1)))
    return format(value.normalize(), "f")
