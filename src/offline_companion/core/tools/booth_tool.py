"""booth_tool：Booth 算法的 builtin Tool 适配。"""

from __future__ import annotations

from offline_companion.core.algorithm_tools import booth_multiply, format_booth_result


def booth_multiply_tool(multiplicand: int, multiplier: int) -> dict[str, object]:
    """摘要：执行 Booth 算法并返回可审计的格式化结果与中间态。"""
    trace = booth_multiply(multiplicand, multiplier)
    return {
        "formatted": format_booth_result(trace),
        "trace": trace,
    }
