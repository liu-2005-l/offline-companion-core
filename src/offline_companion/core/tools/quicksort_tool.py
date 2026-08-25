"""quicksort_tool：快速排序算法的 builtin Tool 适配。"""

from __future__ import annotations

from offline_companion.core.algorithm_tools import format_quicksort_result, quicksort


def quicksort_tool(values: list[int]) -> dict[str, object]:
    """摘要：执行快速排序并返回格式化结果与分区快照。"""
    trace = quicksort(values)
    return {
        "formatted": format_quicksort_result(trace),
        "trace": trace,
    }
