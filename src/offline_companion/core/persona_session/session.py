"""session：人格锁与会话装配（B1）。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from offline_companion.core.memory_lifecycle.recall import format_recall_prompt_block, recall
from offline_companion.shared.types import MemoryRecallHit, MessageRow, Persona


@runtime_checkable
class InferenceBackend(Protocol):
    """摘要：B1 所依赖的 C1 推理后端最小协议。"""

    def generate(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> str: ...


@dataclass(frozen=True)
class AssembleReplyResult:
    """摘要：单轮装配结果。"""

    reply: str
    memory_recalls: list[MemoryRecallHit]
    memory_block: str


class PersonaSessionCore:
    """摘要：围绕单一人设完成上下文装配与本地推理调用。"""

    def __init__(self, persona: Persona) -> None:
        self.persona = persona

    @property
    def system_prompt_locked(self) -> str:
        """摘要：返回受角色锁约束的系统提示文本。"""
        return self.persona.system_prompt

    def assemble_reply(
        self,
        backend: InferenceBackend,
        conn: sqlite3.Connection,
        *,
        user_message: str,
        history: list[MessageRow],
        memory_enabled: bool,
        max_tokens: int = 256,
    ) -> AssembleReplyResult:
        """摘要：装配 prompt、注入记忆召回并调用推理后端。

        参数：
            backend: C1 推理后端（或 Echo）。
            conn: 会话数据库连接。
            user_message: 当前用户消息（已落库或即将落库）。
            history: 不含当前条的近期历史。
            memory_enabled: 是否启用记忆召回注入；为 False 时不召回、不注入。
            max_tokens: 生成 token 上限。

        返回值：
            助手回复文本及本轮召回明细。
        """
        recalls: list[MemoryRecallHit] = []
        memory_block = ""
        if memory_enabled:
            recalls = recall(conn, user_message, limit=8)
            memory_block = format_recall_prompt_block(recalls)

        reply = backend.generate(
            system_prompt=self.system_prompt_locked,
            history=history,
            user_message=user_message,
            memory_block=memory_block,
            max_tokens=max_tokens,
        )
        return AssembleReplyResult(
            reply=reply,
            memory_recalls=recalls,
            memory_block=memory_block,
        )
