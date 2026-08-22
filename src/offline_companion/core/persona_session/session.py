"""session：人格锁与会话装配（B1）。"""

from __future__ import annotations

import logging
import os
import sqlite3
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import yaml

from offline_companion.core.arithmetic_verifier import audit_arithmetic_reply
from offline_companion.core.emotion_analyzer.context import EmotionContext
from offline_companion.core.memory_lifecycle.event_recaller import (
    EventRecaller,
    format_event_narrative,
)
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.recall import format_recall_prompt_block, recall
from offline_companion.core.persona_session.persona_loader import resolved_companion_display_name
from offline_companion.shared.deterministic_embedding import embed_text
from offline_companion.shared.runtime_paths import configs_dir, dev_repo_root
from offline_companion.shared.types import (
    CapabilityProfile,
    MemoryRecallHit,
    MessageRow,
    OceanVector,
    Persona,
)

_EMOTION_STRATEGIES: dict[str, dict[str, str]] | None = None
_OCEAN_TONE_MAPPINGS: dict[str, dict[str, object]] | None = None
_ASSISTANT_NAME_QUESTION_KEYWORDS = ("你叫什么", "你的名字", "你叫啥", "你是谁")
_DISPLAY_NAME_MAX_CHARS = 32
SKILL_BOOTSTRAP_PROMPT = """\
## 技能感知

在处理复杂任务前，检查是否有匹配的技能定义（SKILL.md）。
如果用户请求匹配某 skill 的 description，必须优先按该 skill 的 Iron Laws 和 Procedure 执行。

技能定义位于 skills/ 目录下。每个 skill 的 SKILL.md 声明了：
- When to Use（适用场景）
- Iron Laws（不可绕过的硬规则）
- Procedure（具体执行步骤）
"""

logger = logging.getLogger(__name__)


def _load_yaml_dict(file_name: str) -> dict[str, object]:
    """摘要：按运行时配置优先级加载 YAML 字典。"""
    candidates = [
        configs_dir() / file_name,
        dev_repo_root() / "configs" / file_name,
    ]
    for path in candidates:
        if not path.is_file():
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return raw if isinstance(raw, dict) else {}
    return {}


def _load_emotion_strategies() -> dict[str, dict[str, str]]:
    """摘要：从 ``configs/emotion_mappings.yaml`` 加载情绪策略。"""
    global _EMOTION_STRATEGIES
    if _EMOTION_STRATEGIES is not None:
        return _EMOTION_STRATEGIES
    raw = _load_yaml_dict("emotion_mappings.yaml")
    strategies = raw.get("emotion_strategies", {})
    _EMOTION_STRATEGIES = {k: v for k, v in strategies.items() if isinstance(v, dict)}
    return _EMOTION_STRATEGIES


def _load_ocean_tone_mappings() -> dict[str, dict[str, object]]:
    """摘要：从 ``configs/ocean_tone_mappings.yaml`` 加载 OCEAN 语气映射。"""
    global _OCEAN_TONE_MAPPINGS
    if _OCEAN_TONE_MAPPINGS is not None:
        return _OCEAN_TONE_MAPPINGS
    raw = _load_yaml_dict("ocean_tone_mappings.yaml")
    dimensions = raw.get("dimensions", {})
    _OCEAN_TONE_MAPPINGS = {k: v for k, v in dimensions.items() if isinstance(v, dict)}
    return _OCEAN_TONE_MAPPINGS


def _build_emotion_instruction(emotion_context: EmotionContext | None) -> str:
    """摘要：根据情绪上下文生成系统指令片段。"""
    if emotion_context is None or emotion_context.emotion == "neutral":
        return ""
    strategies = _load_emotion_strategies()
    entry = strategies.get(emotion_context.emotion)
    if entry is None:
        return ""
    instruction = str(entry.get("system_instruction") or "").strip()
    if not instruction:
        return ""
    return f"\n【情绪策略】{instruction}\n"


def _build_tone_instruction(ocean: OceanVector | None) -> str:
    """摘要：根据 OCEAN 向量生成语气风格指令，只描述显著维度。"""
    if ocean is None:
        return ""
    mappings = _load_ocean_tone_mappings()
    descriptors: list[str] = []
    values = {
        "openness": ocean.openness,
        "conscientiousness": ocean.conscientiousness,
        "extraversion": ocean.extraversion,
        "agreeableness": ocean.agreeableness,
        "neuroticism": ocean.neuroticism,
    }
    for dim_name, value in values.items():
        entry = mappings.get(dim_name)
        if entry is None:
            continue
        band = _resolve_ocean_band(entry, value)
        if band == "high":
            descriptors.extend(_descriptor_list(entry.get("descriptors")))
        elif band == "low":
            descriptors.extend(_descriptor_list(entry.get("low_descriptors")))
    if not descriptors:
        return ""
    unique_descriptors = list(dict.fromkeys(descriptors))
    return f"\n【语气风格】语气风格：{', '.join(unique_descriptors)}。\n"


def _resolve_ocean_band(entry: dict[str, object], value: float) -> str | None:
    """摘要：按阈值判断当前维度属于高段、低段或中间段。"""
    high = entry.get("high")
    low = entry.get("low")
    if isinstance(high, (list, tuple)) and len(high) == 2 and float(high[0]) <= value <= float(high[1]):
        return "high"
    if isinstance(low, (list, tuple)) and len(low) == 2 and float(low[0]) <= value <= float(low[1]):
        return "low"
    return None


def _descriptor_list(value: object) -> list[str]:
    """摘要：将配置中的描述列表标准化为字符串列表。"""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _sanitize_display_name(value: object) -> str:
    """摘要：将画像记忆中的自称规范化为安全的单行短文本，避免注入系统提示。"""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    safe_chars: list[str] = []
    for char in text:
        if char in {" ", "-", "_", "·", "・"}:
            safe_chars.append(char)
            continue
        category = unicodedata.category(char)
        if category[0] in {"L", "N"}:
            safe_chars.append(char)
    return "".join(safe_chars).strip()[:_DISPLAY_NAME_MAX_CHARS]


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

    def generate_stream(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> Iterator[str]: ...


@dataclass(frozen=True)
class AssembleReplyResult:
    """摘要：单轮装配结果。"""

    reply: str
    memory_recalls: list[MemoryRecallHit]
    memory_block: str


class PersonaSessionCore:
    """摘要：围绕单一人设完成人上下文装配与本地推理调用。"""

    def __init__(self, persona: Persona) -> None:
        self.persona = persona

    @property
    def system_prompt_locked(self) -> str:
        """摘要：返回受角色锁约束的系统提示文本（含当前陪伴自称）。"""
        return self._system_prompt_locked()

    def _system_prompt_locked(self, conn: sqlite3.Connection | None = None) -> str:
        """摘要：返回角色锁系统提示；若存在助手画像记忆，优先使用记忆中的当前自称。"""
        display = self._resolved_companion_display_name(conn)
        prefix = (
            f"【当前自称】{display}\n"
            "只有用户主动询问你的名字或身份，或当前语境确实需要时，才提及自称；普通寒暄不要主动自我介绍。\n"
            "需要提及名字时必须使用上述标准自称，不要使用名字变体。\n\n"
        )
        return prefix + self.persona.system_prompt

    def _resolved_companion_display_name(self, conn: sqlite3.Connection | None = None) -> str:
        """摘要：解析当前助手自称；长期画像记忆优先于 persona 默认配置。"""
        if conn is not None:
            profile = MemoryLifecycleManager.latest_profile_memory(conn)
            display_name = _sanitize_display_name(profile.get("assistant", {}).get("display_name"))
            if display_name:
                return display_name
        return _sanitize_display_name(resolved_companion_display_name(self.persona))

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
        capability_profile: CapabilityProfile | None = None,
        skill_prompt: str = "",
        audit_arithmetic: bool = True,
    ) -> AssembleReplyResult:
        """摘要：装配 prompt、注入记忆召回与情绪/语气策略并调用推理后端。"""
        recalls, combined_memory_block, system_prompt, identity_reply = self._assemble_context(
            conn,
            user_message=user_message,
            memory_enabled=memory_enabled,
            reference_block=reference_block,
            emotion_context=emotion_context,
            capability_profile=capability_profile,
            skill_prompt=skill_prompt,
        )
        if identity_reply is not None:
            return AssembleReplyResult(
                reply=identity_reply,
                memory_recalls=recalls,
                memory_block=combined_memory_block,
            )

        reply = backend.generate(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            memory_block=combined_memory_block,
            max_tokens=max_tokens,
        )
        audit = (
            audit_arithmetic_reply(
                reply,
                retry=lambda feedback: backend.generate(
                    system_prompt=f"{system_prompt}\n\n【算术校验反馈】\n{feedback}",
                    history=history,
                    user_message=user_message,
                    memory_block=combined_memory_block,
                    max_tokens=max_tokens,
                ),
            )
            if audit_arithmetic
            else None
        )
        return AssembleReplyResult(
            reply=audit.reply if audit is not None else reply,
            memory_recalls=recalls,
            memory_block=combined_memory_block,
        )

    def assemble_reply_stream(
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
        capability_profile: CapabilityProfile | None = None,
        skill_prompt: str = "",
    ) -> Iterator[dict[str, Any]]:
        """????? prompt ??????????????"""
        recalls, combined_memory_block, system_prompt, identity_reply = self._assemble_context(
            conn,
            user_message=user_message,
            memory_enabled=memory_enabled,
            reference_block=reference_block,
            emotion_context=emotion_context,
            capability_profile=capability_profile,
            skill_prompt=skill_prompt,
        )
        yield {"recall": len(recalls)}
        if identity_reply is not None:
            yield {"token": identity_reply}
            yield {"done": True, "reply": identity_reply, "memory_recalls": recalls}
            return
        chunks: list[str] = []
        for token in backend.generate_stream(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            memory_block=combined_memory_block,
            max_tokens=max_tokens,
        ):
            chunks.append(token)
            yield {"token": token}
        raw_reply = "".join(chunks)
        audit = audit_arithmetic_reply(
            raw_reply,
            retry=lambda feedback: backend.generate(
                system_prompt=f"{system_prompt}\n\n【算术校验反馈】\n{feedback}",
                history=history,
                user_message=user_message,
                memory_block=combined_memory_block,
                max_tokens=max_tokens,
            ),
        )
        yield {"done": True, "reply": audit.reply, "memory_recalls": recalls}

    def _assemble_context(
        self,
        conn: sqlite3.Connection,
        *,
        user_message: str,
        memory_enabled: bool,
        reference_block: str = "",
        emotion_context: EmotionContext | None = None,
        capability_profile: CapabilityProfile | None = None,
        skill_prompt: str = "",
    ) -> tuple[list[MemoryRecallHit], str, str, str | None]:
        """??????????profile ? system prompt????????????"""
        profile = capability_profile or CapabilityProfile()
        recalls: list[MemoryRecallHit] = []
        memory_block = ""
        if reference_block.strip():
            memory_block = reference_block.strip()
        elif memory_enabled:
            emotion_label = emotion_context.emotion if emotion_context is not None else None
            recall_limit = 8 if profile.max_context >= 4096 else 4
            recalls = recall(conn, user_message, limit=recall_limit, emotion=emotion_label)
            memory_block = format_recall_prompt_block(recalls)
            semantic_events = EventRecaller(
                EventRepository(conn),
                embed_func=lambda text: embed_text(text, dimensions=768),
            ).recall(user_message, top_k=min(5, recall_limit))
            event_block = format_event_narrative(semantic_events)
            if event_block:
                memory_block = "\n\n".join(part for part in (memory_block, event_block) if part.strip())
        profile_block = self._profile_memory_block(conn) if memory_enabled else ""
        combined_memory_block = "\n\n".join(part for part in (profile_block, memory_block) if part.strip())
        tone_instruction = _build_tone_instruction(self.persona.ocean)
        if profile.roleplay_quality < 0.4:
            tone_instruction = ""
        emotion_instruction = _build_emotion_instruction(emotion_context)
        format_hint = ""
        if profile.instruction_following < 0.4:
            format_hint = "\n【输出要求】请用简洁自然的中文回答，不要重复用户的话。\n"
        prompt_parts = [
            self._system_prompt_locked(conn),
            "涉及数值计算时，给出结果前先做量级估算复核。",
            SKILL_BOOTSTRAP_PROMPT,
        ]
        if skill_prompt.strip():
            prompt_parts.append(skill_prompt.strip())
        system_prompt = "\n\n".join(prompt_parts) + (tone_instruction + emotion_instruction + format_hint)
        if os.getenv("OFFLINE_COMPANION_PROMPT_PROBE") == "1":
            logger.debug("[PROMPT_PROBE] system_prompt=%r", system_prompt[:200])
        identity_reply = self._identity_question_reply(conn, user_message, memory_enabled=memory_enabled)
        return recalls, combined_memory_block, system_prompt, identity_reply

    def _profile_memory_block(self, conn: sqlite3.Connection) -> str:
        profile = MemoryLifecycleManager.latest_profile_memory(conn)
        lines: list[str] = []
        assistant = profile.get("assistant", {})
        user = profile.get("user", {})
        if assistant.get("display_name"):
            display_name = _sanitize_display_name(assistant["display_name"])
            if display_name:
                lines.append(f"- 助手当前自画像：名字 = {display_name}")
        if user.get("display_name"):
            lines.append(f"- 用户当前画像：名字 = {user['display_name']}")
        if user.get("preference"):
            lines.append(f"- 用户长期偏好：{user['preference']}")
        if not lines:
            return ""
        return "【长期画像记忆】\n" + "\n".join(lines)

    def _identity_question_reply(self, conn: sqlite3.Connection, user_message: str, *, memory_enabled: bool) -> str | None:
        """摘要：对助手自称查询做确定性回答，避免小模型忽略画像身份锁。"""
        if not memory_enabled:
            return None
        text = user_message.strip()
        if not any(keyword in text for keyword in _ASSISTANT_NAME_QUESTION_KEYWORDS):
            return None
        display_name = self._resolved_companion_display_name(conn)
        if not display_name:
            return None
        return f"我叫{display_name}。"
