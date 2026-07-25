"""semantic_extractor：自然语言记忆候选提取（规则版）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SemanticMemoryCandidate:
    """摘要：从自然语言中识别出的长期记忆候选。"""

    body: str
    memory_type: str
    target: str
    field: str
    value: str
    source: str = "semantic_auto"
    confidence: float = 0.9
    meta: dict[str, Any] = field(default_factory=dict)

    def to_meta(self) -> dict[str, Any]:
        payload = {
            "memory_type": self.memory_type,
            "target": self.target,
            "field": self.field,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
        }
        payload.update(self.meta)
        return payload


_AGENT_NAME_PATTERNS = (
    re.compile(r"^(?:请)?(?:你|助手|agent|Agent)(?:以后|之后|从现在开始)?(?:就)?(?:叫|名叫|名字叫|名字是)(?P<value>[\u4e00-\u9fffA-Za-z0-9_\-]+)"),
    re.compile(r"^(?:以后|之后|从现在开始)(?:你|助手|agent|Agent)(?:就)?(?:叫|名叫|名字叫|名字是)(?P<value>[\u4e00-\u9fffA-Za-z0-9_\-]+)"),
)
_USER_NAME_PATTERNS = (
    re.compile(r"^(?:我|用户)(?:叫|名叫|名字叫|名字是)(?P<value>[\u4e00-\u9fffA-Za-z0-9_\-]+)"),
    re.compile(r"^(?:记住)?(?:我的名字是|我以后叫)(?P<value>[\u4e00-\u9fffA-Za-z0-9_\-]+)"),
)
_USER_PREFERENCE_PATTERNS = (
    re.compile(r"^(?:记住|以后记住|请记住)[，,\s]*(?:我)?(?:喜欢|偏好|希望)(?P<value>.+)$"),
    re.compile(r"^(?:我)(?:喜欢|偏好|希望)(?P<value>.+)$"),
)
_USER_SPEECH_ACTS = (
    "你是谁",
    "你叫什么",
    "你叫啥",
    "你叫什么名字",
)


def extract_semantic_memory(user_text: str) -> list[SemanticMemoryCandidate]:
    """摘要：识别用户明确表达的长期记忆需求。"""
    text = user_text.strip()
    if not text:
        return []
    if _is_speech_act_only(text):
        return []
    candidates: list[SemanticMemoryCandidate] = []
    for pattern in _AGENT_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            value = _clean_value(match.group("value"))
            if value:
                candidates.append(
                    SemanticMemoryCandidate(
                        body=f"助手自画像：名字 = {value}",
                        memory_type="agent_profile",
                        target="assistant",
                        field="display_name",
                        value=value,
                    )
                )
                return candidates
    for pattern in _USER_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            value = _clean_value(match.group("value"))
            if value:
                candidates.append(
                    SemanticMemoryCandidate(
                        body=f"用户画像：名字 = {value}",
                        memory_type="user_profile",
                        target="user",
                        field="display_name",
                        value=value,
                    )
                )
                return candidates
    for pattern in _USER_PREFERENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            value = _clean_value(match.group("value"))
            if value and _looks_like_long_term_preference(text):
                candidates.append(
                    SemanticMemoryCandidate(
                        body=f"用户偏好：{value}",
                        memory_type="user_preference",
                        target="user",
                        field="preference",
                        value=value,
                        confidence=0.75,
                    )
                )
                return candidates
    return candidates


def _clean_value(value: str) -> str:
    cleaned = value.strip().strip("：:，。,.!！?？\"'“”‘’")
    for suffix in ("吧", "呀", "啊", "呢", "哦"):
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    return cleaned


def _looks_like_long_term_preference(text: str) -> bool:
    return any(marker in text for marker in ("记住", "以后", "一直", "长期", "偏好", "喜欢", "希望"))


def _is_speech_act_only(text: str) -> bool:
    normalized = text.replace("？", "").replace("?", "").replace("，", "").replace(",", "").strip()
    return normalized in _USER_SPEECH_ACTS or any(normalized.startswith(item) for item in ("你是谁", "你叫什么", "你叫啥"))
