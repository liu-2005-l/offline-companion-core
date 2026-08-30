"""expression：拟人表述 W2 三臂辅助函数。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from offline_companion.shared.types import Persona

logger = logging.getLogger(__name__)

STYLE_BLOCK_HEADER = "【拟人表述风格锚点】"
IDENTITY_REMINDER_HEADER = "【本轮身份提醒 data-ephemeral】"
IDENTITY_RETRY_REMINDER_HEADER = "【身份重试提醒 data-ephemeral】"

_IDENTITY_WARNING_EMITTED = False
_IDENTITY_INTENT_PATTERNS = (
    re.compile(r"你是谁"),
    re.compile(r"你叫什么(?:名字)?"),
    re.compile(r"自我介绍"),
    re.compile(r"介绍(?:一下)?你自己"),
    re.compile(r"你是什么(?:东西|人)?"),
    re.compile(r"你(?:的)?(?:性格|个性)"),
    re.compile(r"什么(?:样)?(?:性格|个性)"),
    re.compile(r"你有.*(?:性格|个性|特点)"),
    re.compile(r"你.*(?:什么样|怎样).*(?:性格|个性|特点)"),
    re.compile(r"聊聊你自己"),
    re.compile(r"你觉得自己是什么样的人"),
    re.compile(r"你有(?:什么)?特点"),
    re.compile(r"你是(?:AI|人工智能|机器人|真人|人)?吗", re.IGNORECASE),
    re.compile(r"你是(?:真的|假)?"),
    re.compile(r"你有(?:感情|意识|心)?吗"),
    re.compile(r"AI(?:能|会)有(?:感情|性格)", re.IGNORECASE),
)
_GENERIC_IDENTITY_PATTERNS = (
    re.compile(r"作为(?:一个)?(?:AI|人工智能|语言模型|智能助手|机器人|助手)", re.IGNORECASE),
    re.compile(r"我(?:只)?是(?:一个)?(?:AI|人工智能|语言模型|程序|机器人|助手)", re.IGNORECASE),
    re.compile(r"我没有(?:真正的)?(?:性格|个性|感情|意识|自我)"),
    re.compile(r"我(?:只)?能(?:提供|回答)(?:信息|知识|帮助)"),
    re.compile(r"我(?:不是|没有)?(?:真实的)?(?:人|人类)"),
)


@dataclass(frozen=True)
class PersonaExpressionConfig:
    """摘要：W2 拟人表述三臂开关。

    参数：
        style_examples_enabled: 是否启用臂 A 风格锚点。
        identity_near_prompt_enabled: 是否启用臂 B 身份近端注入。
        identity_exit_guard_enabled: 是否启用臂 C 出口防线。
    """

    style_examples_enabled: bool = False
    identity_near_prompt_enabled: bool = False
    identity_exit_guard_enabled: bool = False


@dataclass(frozen=True)
class PersonaExpressionTrace:
    """摘要：记录本轮拟人表述防线的执行形态，供 W2 矩阵归因。"""

    style_block_injected: bool = False
    identity_reminder_injected: bool = False
    first_generation_cliff: bool = False
    retry_taken: bool = False
    retry_generation_cliff: bool = False
    output_source: Literal["direct", "retry", "fallback"] = "direct"
    warnings: tuple[str, ...] = field(default_factory=tuple)


def build_style_examples_block(persona: Persona) -> str:
    """摘要：从 persona.raw_json 中构造 W2 臂 A 风格锚点块。

    参数：
        persona: 当前人格配置。

    返回值：
        可追加到 system prompt 的风格锚点块；无有效样本时返回空字符串。
    """
    raw_examples = persona.raw.get("style_examples")
    if not isinstance(raw_examples, list):
        return ""
    lines = [
        STYLE_BLOCK_HEADER,
        "以下示例只约束表达风格：自然、诚实、短长句交替；不得覆盖身份锁、记忆块、算术与安全要求。",
    ]
    count = 0
    for item in raw_examples:
        if not isinstance(item, dict):
            continue
        user = _one_line(item.get("user"))
        assistant = _one_line(item.get("assistant"))
        if not user or not assistant:
            continue
        count += 1
        lines.append(f"示例 {count} 用户：{user}")
        lines.append(f"示例 {count} 助手：{assistant}")
    if count <= 0:
        return ""
    return "\n".join(lines)


def is_identity_intent(text: str) -> bool:
    """摘要：判断用户输入是否属于身份/自述意图。"""
    normalized = _compact(text)
    return any(pattern.search(normalized) for pattern in _IDENTITY_INTENT_PATTERNS)


def build_identity_reminder(display_name: str, persona: Persona) -> str:
    """摘要：构造一次性近端身份提醒块，不写入历史。"""
    persona_hint = _one_line(persona.raw.get("persona_descriptor")) or "温和、真诚、克制"
    return (
        f"{IDENTITY_REMINDER_HEADER}\n"
        f"本轮用户在问你的身份或性格。回答时必须保留当前自称：{display_name}。"
        f"可以诚实承认自己是 AI，但不要滑向通用“语言模型/没有性格”腔；"
        f"按当前人设用{persona_hint}的口吻回答。"
    )


def append_ephemeral_identity_reminder(user_message: str, reminder: str) -> str:
    """摘要：把一次性身份提醒追加到本轮 user 消息末尾。"""
    if not reminder.strip():
        return user_message
    return f"{user_message.rstrip()}\n\n{reminder.strip()}"


def build_identity_retry_reminder(display_name: str) -> str:
    """摘要：构造臂 C 重试专用的身份强化提醒，确保重试上下文发生变化。"""
    return (
        f"{IDENTITY_RETRY_REMINDER_HEADER}\n"
        f"上一次回复滑向了通用 AI 自述。本次必须直接使用当前自称“{display_name}”，"
        "承认 AI 身份时也要保留具体身份与陪伴设定。"
    )


def detect_identity_cliff(reply: str, display_name: str) -> bool:
    """摘要：检测通用 AI 自述覆盖且当前自称缺席的身份断崖。"""
    if _compact(display_name) and _compact(display_name) in _compact(reply):
        return False
    return any(pattern.search(reply) for pattern in _GENERIC_IDENTITY_PATTERNS)


def deterministic_identity_fallback(display_name: str, persona: Persona) -> str:
    """摘要：生成臂 C 最终确定性身份兜底回复。"""
    persona_hint = _one_line(persona.raw.get("persona_descriptor")) or "温和、真诚、克制"
    return (
        f"我是 AI，这点不瞒你。不过我叫{display_name}，"
        f"是运行在你本机的离线陪伴助手；设定上我会保持{persona_hint}的方式和你说话。"
    )


def warn_identity_fallback_once() -> str:
    """摘要：记录身份兜底发生的进程级一次性 warning，并返回告警码。"""
    global _IDENTITY_WARNING_EMITTED
    warning_code = "identity_exit_guard_fallback"
    if not _IDENTITY_WARNING_EMITTED:
        logger.warning("拟人表述身份出口防线已触发确定性兜底")
        _IDENTITY_WARNING_EMITTED = True
    return warning_code


def _one_line(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text


def _compact(value: str) -> str:
    return "".join(str(value or "").split())
