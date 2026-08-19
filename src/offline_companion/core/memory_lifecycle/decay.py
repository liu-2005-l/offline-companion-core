"""语义事件的时间衰减与 dormant 判定。"""

from __future__ import annotations

import math
import time

from .event_types import SemanticEvent

DEFAULT_HALF_LIFE_DAYS = 30.0
DEFAULT_MAX_RECALL_BOOST = 2.0


def compute_decay_score(event: SemanticEvent, now: float | None = None, half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    """摘要：按重要性、年龄和召回反馈计算衰减分数。"""
    current = time.time() if now is None else now
    age_days = max(0.0, current - event.created_at) / 86400.0
    decay = math.exp(-age_days / half_life_days) if half_life_days > 0 else 1.0
    recall_boost = min(1.0 + event.recall_count * 0.1, DEFAULT_MAX_RECALL_BOOST)
    return event.importance * decay * recall_boost


def should_gc(event: SemanticEvent, now: float | None = None, threshold: float = 0.1) -> bool:
    """摘要：判断从未召回且分数过低的事件是否应标记 dormant。"""
    return compute_decay_score(event, now) < threshold and event.recall_count == 0
