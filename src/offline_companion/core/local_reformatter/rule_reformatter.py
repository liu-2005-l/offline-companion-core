"""rule_reformatter：规则版 PersonaReformatter（B4）。"""

from __future__ import annotations

from offline_companion.shared.types import Persona


def reformat_cloud_reply(text: str, persona: Persona) -> str:
    """摘要：将云端返回文本用规则管线压回人设风格（Phase 0 直通）。

    参数：
        text: 云端原始文本。
        persona: 当前人设。

    返回值：
        润色后文本；当前实现不做改写，占位保留接口。
    """
    _ = persona
    return text
