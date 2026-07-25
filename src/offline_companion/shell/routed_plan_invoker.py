"""routed_plan_invoker：按 route_mode 选择不同执行后端。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from offline_companion.core.plan_orchestrator import PlanStep, TaskContext
from offline_companion.shared.types import CloudCompletionRequest
from offline_companion.shell.outbound_manager.connector import post_cloud_completion


class RouteInvoker(Protocol):
    def invoke(self, skill_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        ...


@dataclass
class CloudRouteInvoker:
    """摘要：真实云端调用链适配器。"""

    purpose: str = "plan_step_execution"
    cloud_post: Any = post_cloud_completion

    def invoke(self, skill_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        request_payload = {
            "skill_id": skill_id,
            "payload": payload,
            "idempotency_key": idempotency_key,
        }
        response = self.cloud_post(
            CloudCompletionRequest(
                user_message=json.dumps(request_payload, ensure_ascii=False),
                purpose=self.purpose,
            )
        )
        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
            return {"result": response.text}


@dataclass
class EchoRouteInvoker:
    """摘要：ECHO 模式兜底执行器。"""

    def invoke(self, skill_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        return {
            "skill_id": skill_id,
            "idempotency_key": idempotency_key,
            "echo": payload,
        }


@dataclass
class RoutedPlanInvoker:
    """摘要：根据 task.context_vars['route_mode'] 选择执行器。"""

    local_invoker: RouteInvoker
    cloud_invoker: RouteInvoker | None = None
    echo_invoker: RouteInvoker | None = None

    def invoke(self, skill_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        mode = str(payload.get("_route_mode") or "local")
        if mode == "cloud" and self.cloud_invoker is not None:
            return self.cloud_invoker.invoke(skill_id, payload, idempotency_key)
        if mode == "echo" and self.echo_invoker is not None:
            return self.echo_invoker.invoke(skill_id, payload, idempotency_key)
        return self.local_invoker.invoke(skill_id, payload, idempotency_key)

    def invoke_step(self, step: PlanStep, context: TaskContext) -> Any:
        payload = dict(step.payload)
        payload["_route_mode"] = str(context.context_vars.get("route_mode") or "local")
        payload["_fallback_chain"] = list(context.context_vars.get("fallback_chain") or [])
        payload["_fallback_index"] = int(context.context_vars.get("fallback_index", 0) or 0)
        return self.invoke(step.skill_id, payload, step.idempotency_key)
