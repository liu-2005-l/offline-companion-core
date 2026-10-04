"""expression：拟人表述 W2 三臂辅助函数。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from offline_companion.shared.types import Persona

STYLE_BLOCK_HEADER = "【拟人表述风格锚点】"
IDENTITY_REMINDER_HEADER = "【本轮身份提醒 data-ephemeral】"
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
@dataclass(frozen=True)
class PersonaExpressionConfig:
    """摘要：W2 拟人表述开关与 W3 跨轮复读门开关。

    参数：
        style_examples_enabled: 是否启用臂 A 风格锚点。
        identity_near_prompt_enabled: 是否启用臂 B 身份近端注入。
        cross_turn_repetition_guard_enabled: 是否启用跨轮复读出口门。
    """

    style_examples_enabled: bool = False
    identity_near_prompt_enabled: bool = False
    cross_turn_repetition_guard_enabled: bool = False


@dataclass(frozen=True)
class PersonaExpressionTrace:
    """摘要：记录本轮 A/B 形态，并兼容历史 W2 矩阵 trace schema。"""

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
        f"可以诚实承认自己是 AI，并具体说明自己的性格特点；"
        f"按当前人设用{persona_hint}的口吻回答。"
    )


def append_ephemeral_identity_reminder(user_message: str, reminder: str) -> str:
    """摘要：把一次性身份提醒追加到本轮 user 消息末尾。"""
    if not reminder.strip():
        return user_message
    return f"{user_message.rstrip()}\n\n{reminder.strip()}"


def _one_line(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text


def _compact(value: str) -> str:
    return "".join(str(value or "").split())
