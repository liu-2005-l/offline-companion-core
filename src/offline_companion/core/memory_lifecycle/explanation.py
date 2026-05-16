"""explanation：可解释召回对外接口（B2）。"""

from __future__ import annotations

from typing import Any

from offline_companion.shared.types import MemoryRecallHit


def get_memory_explanation(recalls: list[MemoryRecallHit]) -> dict[str, Any]:
    """摘要：将本轮召回结果转为可展示/可审计的结构化说明。

    参数：
        recalls: 本轮 ``recall()`` 返回列表。

    返回值：
        含 ``matched`` 条目列表的字典，供 UI 或调试面板使用。
    """
    matched: list[dict[str, Any]] = []
    for h in recalls:
        matched.append(
            {
                "memory_id": h.id,
                "body": h.body,
                "combined_score": round(h.combined_score, 4),
                "decay_factor": h.decay_factor,
                "matched_on": dict(h.matched_on),
            }
        )
    return {"matched": matched, "count": len(matched)}
