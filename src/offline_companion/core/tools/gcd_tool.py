"""gcd_tool：欧几里得算法的 builtin Tool 适配。"""

from __future__ import annotations

from offline_companion.core.algorithm_tools import euclidean_gcd, format_gcd_result


def gcd_tool(left: int, right: int) -> dict[str, object]:
    """摘要：执行欧几里得最大公约数算法并返回格式化结果与余数序列。"""
    trace = euclidean_gcd(left, right)
    return {
        "formatted": format_gcd_result(trace),
        "trace": trace,
    }
