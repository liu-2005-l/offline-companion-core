"""calculator_tool：基础算术的 builtin Tool 适配。"""

from __future__ import annotations

from offline_companion.core.calculator import calculate_expression


def calculator_tool(left: str | int, operator: str, right: str | int) -> dict[str, object]:
    """摘要：执行基础算术并返回可审计结果。"""
    result = calculate_expression(left, operator, right)
    return {
        **result,
        "left": str(result["left"]),
        "right": str(result["right"]),
        "result": str(result["result"]),
    }
