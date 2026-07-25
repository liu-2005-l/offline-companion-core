"""memory_schema：统一记忆实体定义。

列职责说明：
- content：记忆的摘要/标题（用于 FTS 索引和快速展示）。
- body：记忆的完整正文（用于详细展示和 prompt 注入）。
- metadata：JSON 字符串，存储结构化元数据（如来源、标签等）。
- meta_json：JSON 字符串，存储语义抽取器产生的原始元数据（如 target / field / value）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from offline_companion.shared.errors import B2MemoryWriteError

MEMORY_TYPES = {
    "fact",
    "habit",
    "preference",
    "context_summary",
    "goal",
    "assistant_profile",
    "user_profile",
    "task_context",
}

MEMORY_STATUSES = {"active", "cancelled", "invalid"}

MEMORY_SOURCES = {
    "user_explicit",
    "auto_compression",
    "self_reflection",
    "semantic_auto",
    "explicit_command",
}


@dataclass(frozen=True)
class MemoryRecord:
    """摘要：统一记忆实体。

    与数据库 memory_chunks 表列对齐：
    - content ↔ content（摘要/标题）
    - body ↔ body（完整正文）
    - metadata ↔ metadata（结构化元数据 JSON）
    - meta_json ↔ meta_json（语义抽取原始元数据 JSON）

    参数：
        id: 自增主键（None 表示未持久化）。
        content: 记忆摘要/标题。
        body: 记忆完整正文。
        memory_type: 记忆类型（见 MEMORY_TYPES）。
        status: 状态（active / cancelled / invalid）。
        source: 来源（见 MEMORY_SOURCES）。
        created_at: 创建时间（ISO 8601 字符串）。
        modified_at: 修改时间（ISO 8601 字符串）。
        metadata: 结构化元数据字典。
        meta_json: 语义抽取原始元数据字典。
    """

    id: int | None
    content: str
    body: str | None = None
    memory_type: str = "fact"
    status: str = "active"
    source: str = "user_explicit"
    created_at: str | None = None
    modified_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    meta_json: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """摘要：校验字段合法性。

        Raises:
            ValueError: 当 memory_type / status / source 不在允许集合内时。
        """
        if self.memory_type not in MEMORY_TYPES:
            raise B2MemoryWriteError(f"invalid memory_type: {self.memory_type}")
        if self.status not in MEMORY_STATUSES:
            raise B2MemoryWriteError(f"invalid memory status: {self.status}")
        if self.source not in MEMORY_SOURCES:
            raise B2MemoryWriteError(f"invalid memory source: {self.source}")
