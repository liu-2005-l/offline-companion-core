"""事件流的领域事件类型。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    """不可变的领域事件信封。

    参数：
        event_id: 事件唯一标识。
        stream_id: 事件所属流的标识。
        seq: 事件在流中的顺序号。
        event_type: 注册的事件类型。
        timestamp: 事件产生时间戳。
        schema_version: 事件负载的结构版本。
        payload: JSON 可序列化的事件负载。
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stream_id: str = ""
    seq: int = 0
    event_type: str = ""
    timestamp: float = 0.0
    schema_version: int = 1
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """校验事件负载的基础约束。"""
        if not isinstance(self.payload, dict):
            raise TypeError("事件 payload 必须是 dict")
        try:
            json.dumps(self.payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("事件 payload 必须可 JSON 序列化") from exc
