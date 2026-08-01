"""memory_schema：记忆主表结构与迁移辅助。"""

from __future__ import annotations

from dataclasses import dataclass

MEMORY_TYPES = (
    "fact",
    "habit",
    "preference",
    "context_summary",
    "goal",
    "agent_profile",
    "user_profile",
    "task_context",
)

MEMORY_STATUSES = ("active", "cancelled")

MEMORY_SOURCES = (
    "user_explicit",
    "auto_compression",
    "self_reflection",
    "semantic_auto",
    "explicit_command",
)


@dataclass(frozen=True)
class MemorySchemaField:
    name: str
    type: str
    description: str


FIELDS: tuple[MemorySchemaField, ...] = (
    MemorySchemaField("id", "INTEGER", "主键，唯一ID"),
    MemorySchemaField("content", "TEXT", "记忆内容"),
    MemorySchemaField("memory_type", "TEXT", "记忆类型枚举"),
    MemorySchemaField("status", "TEXT", "状态枚举"),
    MemorySchemaField("created_at", "TEXT", "创建时间，ISO 8601"),
    MemorySchemaField("modified_at", "TEXT", "最后修改时间，ISO 8601"),
    MemorySchemaField("source", "TEXT", "来源标记"),
    MemorySchemaField("metadata", "TEXT (JSON)", "扩展元数据"),
)


def is_known_memory_type(value: str) -> bool:
    return value in MEMORY_TYPES


def is_known_memory_status(value: str) -> bool:
    return value in MEMORY_STATUSES


def is_known_memory_source(value: str) -> bool:
    return value in MEMORY_SOURCES
