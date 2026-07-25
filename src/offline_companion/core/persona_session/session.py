"""session：人格锁与会话装配（B1）。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import yaml

from offline_companion.core.emotion_analyzer.context import EmotionContext
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.recall import format_recall_prompt_block, recall
from offline_companion.core.persona_session.persona_loader import resolved_companion_display_name
from offline_companion.shared.runtime_paths import configs_dir
from offline_companion.shared.types import MemoryRecallHit, MessageRow, Persona

# ── 情绪策略配置加载（惰性） ─────────────────────────────────────
_EMOTION_STRATEGIES: dict[str, dict[str, str]] | None = None


def _load_emotion_strategies() -> dict[str, dict[str, str]]:
    """摘要：从 ``configs/emotion_mappings.yaml`` 加载情绪策略。"""
    global _EMOTION_STRATEGIES
    if _EMOTION_STRATEGIES is not None:
        return _EMOTION_STRATEGIES
    path = configs_dir() / "emotion_mappings.yaml"
    if not path.is_file():
        _EMOTION_STRATEGIES = {}
        return _EMOTION_STRATEGIES
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    strategies = raw.get("emotion_strategies", {})
    _EMOTION_STRATEGIES = {k: v for k, v in strategies.items() if isinstance(v, dict)}
    return _EMOTION_STRATEGIES


def _build_emotion_instruction(emotion_context: EmotionContext | None) -> str:
    """摘要：根据情绪上下文生成系统指令片段。

    参数：
        emotion_context: B0 输出的情绪上下文；为 None 时返回空字符串。

    返回值：
        情绪策略系统指令文本（含换行），无匹配时返回空字符串。
    """
    if emotion_context is None or emotion_context.emotion == "neutral":
        return ""
    strategies = _load_emotion_strategies()
    entry = strategies.get(emotion_context.emotion)
    if entry is None:
        return ""
    instruction = entry.get("system_instruction", "")
    if not instruction:
        return ""
    return f"\n【情绪策略】{instruction}\n"


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
        """摘要：返回受角色锁约束的系统提示文本（含当前陪伴自称）。"""
        display = resolved_companion_display_name(self.persona)
        # 自称由宿主注册或 default；避免在 YAML 中写死固定昵称
        prefix = (
            f"【当前自称】{display}\n"
            "你必须始终使用上述自称；不要把它变形成语法变化后的名字。\n"
            "若输出中出现名字变体，优先修正为标准自称。\n\n"
        )
        return prefix + self.persona.system_prompt

    def assemble_reply(
        self,
        backend: InferenceBackend,
        conn: sqlite3.Connection,
        *,
        user_message: str,
        history: list[MessageRow],
        memory_enabled: bool,
        max_tokens: int = 256,
        reference_block: str = "",
        emotion_context: EmotionContext | None = None,
    ) -> AssembleReplyResult:
        """摘要：装配 prompt、注入记忆召回与情绪策略并调用推理后端。

        参数：
            backend: C1 推理后端（或 Echo）。
            conn: 会话数据库连接。
            user_message: 当前用户消息（已落库或即将落库）。
            history: 不含当前条的近期历史。
            memory_enabled: 是否启用记忆召回注入；为 False 时不召回、不注入。
            max_tokens: 生成 token 上限。
            reference_block: 外部参考块（如知识检索）；非空时优先于记忆块。
            emotion_context: B0 输出的情绪上下文；为 None 时不注入情绪策略。

        返回值：
            助手回复文本及本轮召回明细。
        """
        recalls: list[MemoryRecallHit] = []
        memory_block = ""
        if reference_block.strip():
            memory_block = reference_block.strip()
        elif memory_enabled:
            recalls = recall(conn, user_message, limit=8)
            memory_block = format_recall_prompt_block(recalls)

        profile_block = self._profile_memory_block(conn) if memory_enabled else ""
        combined_memory_block = "\n\n".join(part for part in (profile_block, memory_block) if part.strip())

        # 情绪策略注入
        emotion_instruction = _build_emotion_instruction(emotion_context)
        system_prompt = self.system_prompt_locked + emotion_instruction

        reply = backend.generate(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            memory_block=combined_memory_block,
            max_tokens=max_tokens,
        )
        return AssembleReplyResult(
            reply=reply,
            memory_recalls=recalls,
            memory_block=combined_memory_block,
        )

    def _profile_memory_block(self, conn: sqlite3.Connection) -> str:
        profile = MemoryLifecycleManager.latest_profile_memory(conn)
        lines: list[str] = []
        assistant = profile.get("assistant", {})
        user = profile.get("user", {})
        if assistant.get("display_name"):
            lines.append(f"- 助手当前自画像：名字 = {assistant['display_name']}")
        if user.get("display_name"):
            lines.append(f"- 用户当前画像：名字 = {user['display_name']}")
        if user.get("preference"):
            lines.append(f"- 用户长期偏好：{user['preference']}")
        if not lines:
            return ""
        return "【长期画像记忆】\n" + "\n".join(lines)
