"""router_advisor：路由建议层（规则 + 可选 LLM）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from offline_companion.shared.types import CloudCompletionRequest
from offline_companion.shell.auto_router import (
    RouterAdvisor,
    RoutingContext,
    RoutingDecision,
    RoutingMode,
)
from offline_companion.shell.outbound_manager.connector import post_cloud_completion


@dataclass
class RuleBasedRouterAdvisor(RouterAdvisor):
    """摘要：纯规则建议层，可在没有 LLM 时提供稳定兜底。"""

    def advise(self, context: RoutingContext, candidates: tuple[RoutingMode, ...]) -> RoutingDecision | None:
        if context.metadata.get("force_cloud") and RoutingMode.CLOUD in candidates:
            return RoutingDecision(
                mode=RoutingMode.CLOUD,
                reason="rule_force_cloud",
                confidence=0.9,
                requires_consent=bool(context.metadata.get("requires_consent")),
                selected_by="rule",
            )
        if context.metadata.get("force_echo") and RoutingMode.ECHO in candidates:
            return RoutingDecision(
                mode=RoutingMode.ECHO,
                reason="rule_force_echo",
                confidence=0.95,
                requires_consent=bool(context.metadata.get("requires_consent")),
                selected_by="rule",
            )
        if context.metadata.get("requires_consent"):
            return RoutingDecision(
                mode=RoutingMode.LOCAL,
                reason="advisor_requires_consent",
                confidence=0.7,
                requires_consent=True,
                selected_by="rule",
            )
        return None


@dataclass
class LLMRouterAdvisor(RouterAdvisor):
    """摘要：调用 A3 出站补全接口的路由建议层。"""

    purpose: str = "cloud_routing"
    cloud_post: Any = post_cloud_completion
    fallback_advisor: RouterAdvisor | None = None
    prompt_prefix: str = "You are a routing assistant. Return JSON with mode and reason."

    def advise(self, context: RoutingContext, candidates: tuple[RoutingMode, ...]) -> RoutingDecision | None:
        if self.fallback_advisor is not None:
            fallback = self.fallback_advisor.advise(context, candidates)
            if fallback is not None:
                return fallback

        prompt = {
            "query": context.query,
            "privacy_mode": context.privacy_mode,
            "complexity": context.complexity,
            "cloud_cost": context.cloud_cost,
            "cloud_budget": context.cloud_budget,
            "candidates": [mode.value for mode in candidates],
            "metadata": dict(context.metadata),
            "output_schema": {
                "mode": "local|cloud|echo",
                "reason": "string",
                "confidence": "number 0..1",
            },
        }
        try:
            response = self.cloud_post(
                CloudCompletionRequest(
                    user_message=f"{self.prompt_prefix}\n{json.dumps(prompt, ensure_ascii=False)}",
                    purpose=self.purpose,
                )
            )
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            return None

        mode_raw = str(payload.get("mode", "")).strip().lower()
        mode_map = {m.value: m for m in RoutingMode}
        mode = mode_map.get(mode_raw)
        if mode is None or mode not in candidates:
            return None

        reason = str(payload.get("reason") or "llm_selected")
        try:
            confidence = float(payload.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
        confidence = max(0.0, min(1.0, confidence))
        return RoutingDecision(
            mode=mode,
            reason=reason,
            confidence=confidence,
            requires_consent=bool(payload.get("requires_consent", context.metadata.get("requires_consent", False))),
            selected_by="llm",
        )
