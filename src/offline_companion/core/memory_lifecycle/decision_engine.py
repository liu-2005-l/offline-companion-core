"""decision_engine：统一的记忆意图与策略决策引擎。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .semantic_extractor import SemanticMemoryCandidate, extract_semantic_memory


@dataclass(frozen=True)
class MemoryDecision:
    """摘要：统一记忆决策结果。"""

    route: str
    should_store: bool
    needs_confirmation: bool = False
    confirm_prompt: str | None = None
    candidate: SemanticMemoryCandidate | None = None
    memory_item: dict[str, Any] | None = None
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class MemoryDecisionEngine:
    """摘要：把记忆识别、策略判断与可写对象生成合并为一体。"""

    def decide(self, user_text: str) -> MemoryDecision:
        text = (user_text or "").strip()
        if not text:
            return MemoryDecision(route="ignore", should_store=False, reason="empty_input")

        candidate = self._parse_explicit_memory(text)
        if candidate is None:
            semantic_candidates = extract_semantic_memory(text)
            candidate = semantic_candidates[0] if semantic_candidates else None

        if candidate is None:
            return MemoryDecision(route="chat", should_store=False, reason="no_memory_signal")

        if self._is_ambiguous(candidate, text):
            return MemoryDecision(
                route="clarify",
                should_store=False,
                needs_confirmation=True,
                candidate=candidate,
                confirm_prompt=self._build_clarify_prompt(candidate),
                reason="ambiguous_memory_intent",
            )

        memory_item = self._candidate_to_memory_item(candidate)
        return MemoryDecision(
            route="memory",
            should_store=True,
            candidate=candidate,
            memory_item=memory_item,
            reason="high_confidence_memory_intent",
            meta={"memory_type": candidate.memory_type, "target": candidate.target},
        )

    def _parse_explicit_memory(self, text: str) -> SemanticMemoryCandidate | None:
        prefixes = ("记忆：", "记住：", "请记住：")
        for prefix in prefixes:
            if text.startswith(prefix):
                content = text[len(prefix) :].strip()
                if not content:
                    return None
                return SemanticMemoryCandidate(
                    body=content,
                    memory_type="task_context",
                    target="task",
                    field="note",
                    value=content,
                    source="explicit_command",
                    confidence=1.0,
                )
        return None

    def _is_ambiguous(self, candidate: SemanticMemoryCandidate, text: str) -> bool:
        return candidate.memory_type == "assistant_profile" and self._looks_like_style_description(text)

    def _build_clarify_prompt(self, candidate: SemanticMemoryCandidate) -> str:
        if candidate.memory_type == "assistant_profile":
            return "好的，我理解您希望我更新助手自画像。您是想修改名字、语气，还是整体风格？"
        return "好的，我想确认一下：这条内容需要作为长期记忆保存吗？"

    def _candidate_to_memory_item(self, candidate: SemanticMemoryCandidate) -> dict[str, Any]:
        return {
            "body": candidate.body,
            "memory_type": candidate.memory_type,
            "target": candidate.target,
            "field": candidate.field,
            "value": candidate.value,
            "status": "active",
            "scope": "session",
            "confidence": candidate.confidence,
            "source": candidate.source,
            "meta_json": candidate.to_meta(),
        }

    def _looks_like_style_description(self, text: str) -> bool:
        style_markers = ("像", "风格", "语气", "口吻", "说话方式", "表达方式")
        return any(marker in text for marker in style_markers) and not any(keyword in text for keyword in ("叫", "名字", "称呼"))
