"""explanation：可解释召回接口（Phase 0 占位）。"""

from __future__ import annotations

from typing import Any


def get_memory_explanation(last_n_turns: int = 5) -> dict[str, Any]:
    """摘要：返回最近若干轮相关的记忆召回解释（占位实现）。

    参数：
        last_n_turns: 最近轮次窗口。

    返回值：
        结构化解释字典；后续填充 matched_on 等字段。
    """
    return {"last_n_turns": last_n_turns, "matched": [], "note": "Phase 0 stub"}
