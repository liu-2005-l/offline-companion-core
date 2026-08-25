"""crc32_tool：CRC-32 算法的 builtin Tool 适配。"""

from __future__ import annotations

from offline_companion.core.algorithm_tools import crc32_utf8, format_crc32_result


def crc32_tool(text: str) -> dict[str, object]:
    """摘要：执行 CRC-32 UTF-8 校验并返回格式化结果与按位轨迹。"""
    trace = crc32_utf8(text)
    return {
        "formatted": format_crc32_result(trace),
        "trace": trace,
    }
