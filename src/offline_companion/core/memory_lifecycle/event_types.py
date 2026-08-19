"""语义事件的数据结构与字段约束。"""

from __future__ import annotations

from dataclasses import dataclass, field

EVENT_TYPES = frozenset({
    "fact",
    "preference",
    "relationship",
    "emotional",
    "decision",
    "milestone",
})
EVENT_STATUSES = frozenset({"active", "dormant", "superseded"})


@dataclass(frozen=True)
class SemanticEvent:
    """摘要：表示一条可跨会话召回的语义事件。

    参数：
        event_id: 事件唯一标识。
        event_type: 事件类型，必须属于 ``EVENT_TYPES``。
        subject: 事件主体，例如 ``user`` 或 ``topic:project``。
        content: 事件的一句话语义描述。
        content_embedding: 可选的内容向量。
        emotional_valence: 情感效价，范围为 -1.0 到 1.0。
        emotional_arousal: 情感唤醒度，范围为 0.0 到 1.0。
        importance: 重要性，范围为 0.0 到 5.0。
        temporal_marker: 日期或会话轮次范围。
        source_turns: 来源会话轮次。
        related_events: 关联事件 ID。
        superseded_by: 替代本事件的新事件 ID。
        created_at: 创建时间戳。
        last_recalled_at: 最近召回时间戳。
        recall_count: 召回次数。
        status: 生命周期状态。
    """

    event_id: str
    event_type: str
    subject: str
    content: str
    content_embedding: list[float] | None = None
    emotional_valence: float = 0.0
    emotional_arousal: float = 0.0
    importance: float = 1.0
    temporal_marker: str = ""
    source_turns: list[int] = field(default_factory=list)
    related_events: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    created_at: float = 0.0
    last_recalled_at: float = 0.0
    recall_count: int = 0
    status: str = "active"

    def validate(self) -> None:
        """摘要：校验事件字段，拒绝无法安全入库的数据。

        异常：
            ValueError: 字段不符合语义事件约束时抛出。
        """
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"invalid event_type: {self.event_type}")
        if not self.subject.strip() or not self.content.strip():
            raise ValueError("subject and content must not be empty")
        if not -1.0 <= self.emotional_valence <= 1.0:
            raise ValueError("emotional_valence must be between -1.0 and 1.0")
        if not 0.0 <= self.emotional_arousal <= 1.0:
            raise ValueError("emotional_arousal must be between 0.0 and 1.0")
        if not 0.0 <= self.importance <= 5.0:
            raise ValueError("importance must be between 0.0 and 5.0")
        if self.recall_count < 0:
            raise ValueError("recall_count must not be negative")
        if self.status not in EVENT_STATUSES:
            raise ValueError(f"invalid event status: {self.status}")
