"""周期性从会话消息中提取并去重语义事件。"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .event_repository import EventRepository
from .event_types import EVENT_TYPES, SemanticEvent

EXTRACTION_INTERVAL = 10
logger = logging.getLogger(__name__)


class EventExtractor:
    """摘要：调用 LLM 结构化提取事件，并写入语义事件仓库。

    参数：
        repo: 语义事件仓库。
        llm_backend: 提供 ``generate(prompt, temperature=...)`` 的后端。
        embedding_func: 将事件文本转换为向量的函数。
        extraction_interval: 自动提取的轮次间隔。
    """

    def __init__(
        self,
        repo: EventRepository,
        llm_backend: Any,
        embedding_func: Callable[[str], list[float]],
        extraction_interval: int = EXTRACTION_INTERVAL,
    ) -> None:
        if extraction_interval <= 0:
            raise ValueError("extraction_interval must be positive")
        self._repo = repo
        self._llm = llm_backend
        self._embed = embedding_func
        self._extraction_interval = extraction_interval
        self.last_extracted_turn = 0

    def should_extract(self, turn_count: int) -> bool:
        """摘要：判断当前轮次是否到达周期性提取边界。"""
        return turn_count > 0 and turn_count % self._extraction_interval == 0

    def mark_extracted(self, turn_count: int) -> None:
        """摘要：记录本次会话已处理到的轮次，供空闲补提取使用。"""
        self.last_extracted_turn = max(self.last_extracted_turn, turn_count)

    def extract(
        self,
        messages: Sequence[Mapping[str, Any]],
        session_id: str,
        turn_range: tuple[int, int],
    ) -> list[SemanticEvent]:
        """摘要：从消息窗口提取、去重并存储语义事件。

        参数：
            messages: 包含 ``role`` 与 ``content`` 的消息序列。
            session_id: 来源会话 ID。
            turn_range: 消息覆盖的起止轮次。
        返回值：实际新写入仓库的事件列表。
        """
        if not messages or turn_range[0] > turn_range[1]:
            return []
        raw_events = self._llm_extract(self._build_prompt(messages))
        stored: list[SemanticEvent] = []
        for raw in raw_events:
            event = self._to_event(raw, session_id, turn_range)
            if event is None or self._is_duplicate(event):
                continue
            self._repo.store(event)
            stored.append(event)
        logger.info(
            "semantic extractor extracted %d events from turns %d-%d candidates=%d",
            len(stored),
            turn_range[0],
            turn_range[1],
            len(raw_events),
        )
        return stored

    def _to_event(
        self,
        raw: Mapping[str, Any],
        session_id: str,
        turn_range: tuple[int, int],
    ) -> SemanticEvent | None:
        event_type = raw.get("event_type")
        content = raw.get("content")
        if event_type not in EVENT_TYPES or not isinstance(content, str) or not content.strip():
            return None
        try:
            event = SemanticEvent(
                event_id=uuid.uuid4().hex,
                event_type=event_type,
                subject=str(raw.get("subject") or "user"),
                content=content.strip(),
                content_embedding=self._embed(content.strip()),
                emotional_valence=float(raw.get("emotional_valence", 0.0)),
                emotional_arousal=float(raw.get("emotional_arousal", 0.0)),
                importance=float(raw.get("importance", 1.0)),
                temporal_marker=f"session:{session_id}:turn:{turn_range[0]}-{turn_range[1]}",
                source_turns=list(range(turn_range[0], turn_range[1] + 1)),
                created_at=time.time(),
            )
            event.validate()
        except (TypeError, ValueError):
            return None
        return event

    def _is_duplicate(self, event: SemanticEvent) -> bool:
        """摘要：相似度达到 0.85 时跳过重复事件。"""
        if not event.content_embedding:
            return False
        for existing, distance in self._repo.vector_search(event.content_embedding, top_k=5):
            if existing.event_type != event.event_type or existing.subject != event.subject:
                continue
            if 1.0 - distance >= 0.85:
                return True
        return False

    @staticmethod
    def _build_prompt(messages: Sequence[Mapping[str, Any]]) -> str:
        """摘要：构造要求返回 JSON 数组的结构化提取提示词。"""
        transcript = "\n".join(
            f"{message.get('role', 'user')!s}: {message.get('content', '')!s}"
            for message in messages
        )
        event_types = ", ".join(sorted(EVENT_TYPES))
        return (
            "你是语义事件提取器。只提取有长期价值的信息，闲聊和临时过程信息返回空数组。\n"
            f"event_type 只能是：{event_types}\n"
            "每个事件必须包含 event_type、subject、content、"
            "emotional_valence(-1到1)、emotional_arousal(0到1)、importance(0到5)。\n"
            "只返回 JSON 数组，不要 Markdown 或解释文字。\n\n"
            f"对话：\n{transcript}"
        )

    def _llm_extract(self, prompt: str) -> list[Mapping[str, Any]]:
        """摘要：调用 LLM 并容错解析裸 JSON 或 Markdown JSON。"""
        try:
            response = self._llm.generate(prompt, temperature=0.3)
        except TypeError:
            try:
                response = self._llm.generate(
                    system_prompt=prompt,
                    history=[],
                    user_message="",
                    max_tokens=1024,
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                return []
        except (OSError, RuntimeError, ValueError):
            return []
        if not isinstance(response, str):
            return []
        candidate = response.strip()
        fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", candidate, re.DOTALL | re.IGNORECASE)
        if fenced:
            candidate = fenced.group(1)
        else:
            match = re.search(r"\[.*\]", candidate, re.DOTALL)
            if match:
                candidate = match.group(0)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, Mapping)]
