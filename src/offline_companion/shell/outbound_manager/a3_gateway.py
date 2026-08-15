"""a3_gateway：A3 审批入口与弹窗决策回写。"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from offline_companion.core.event_stream import EventStream
from offline_companion.core.plan_orchestrator import ConsentRequest
from offline_companion.shared.types import PurposeType
from offline_companion.shell.outbound_manager.consent import persist_consent_artifact

DecisionProvider = Callable[[dict[str, Any]], bool]


def _purpose_for_request(consent_request: ConsentRequest) -> str:
    raw_purpose = consent_request.purpose_type or consent_request.metadata.get("purpose_type") or ""
    explicit = raw_purpose.value if isinstance(raw_purpose, PurposeType) else str(raw_purpose).strip()
    if explicit:
        return explicit
    skill = (consent_request.skill_id or "").lower()
    if "network" in skill or "egress" in skill:
        return PurposeType.SKILL_NETWORK_EGRESS.value
    if "file" in skill:
        return PurposeType.SKILL_FILE_ACCESS.value
    if "code" in skill or "exec" in skill:
        return PurposeType.SKILL_CODE_EXECUTION.value
    if "cloud" in skill:
        return PurposeType.SKILL_CLOUD_INFERENCE.value
    if consent_request.risk_level == "high":
        return PurposeType.PLUGIN_HIGH_RISK_SKILL.value
    return PurposeType.NATIVE_RISK_PROMPT.value


def build_consent_artifact(
    consent_request: ConsentRequest,
    *,
    user_decision: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """构造可被 A3 校验/落库的 Consent Artifact。"""
    return {
        "request_id": request_id or str(uuid.uuid4()),
        "scope": "this_turn",
        "purpose": _purpose_for_request(consent_request),
        "user_decision": user_decision,
        "timestamp": time.time(),
        "data_category": "plan_step",
        "plan_id": consent_request.plan_id,
        "step_id": consent_request.step_id,
        "skill_id": consent_request.skill_id,
        "operation": consent_request.operation,
        "risk_level": consent_request.risk_level,
        "impact_scope": consent_request.impact_scope,
        "source": consent_request.source,
        "metadata": dict(consent_request.metadata),
    }


@dataclass
class PendingConsent:
    """等待用户决策的 Consent 请求。"""

    request_id: str
    consent_request: ConsentRequest
    artifact: dict[str, Any]
    decided: bool = False
    allowed: bool = False


@dataclass
class UIHostConsentGateway:
    """真正的 A3 审批入口：构造 artifact、展示弹窗、回写决策。"""

    decision_provider: DecisionProvider | None = None
    db_conn: sqlite3.Connection | None = None
    event_stream: EventStream | None = None
    pending: dict[str, PendingConsent] = field(default_factory=dict)
    last_artifact: dict[str, Any] | None = None

    def submit(self, consent_request: ConsentRequest) -> bool:
        request_id = str(uuid.uuid4())
        artifact = build_consent_artifact(consent_request, user_decision="pending", request_id=request_id)
        pending = PendingConsent(
            request_id=request_id,
            consent_request=consent_request,
            artifact=artifact,
        )
        self.pending[request_id] = pending
        self.last_artifact = artifact
        if self.event_stream is not None:
            self.event_stream.append(
                "consent/asked",
                {
                    "request_id": request_id,
                    "plan_id": consent_request.plan_id,
                    "step_id": consent_request.step_id,
                    "purpose": _purpose_for_request(consent_request),
                    "risk_level": consent_request.risk_level,
                    "trace_id": consent_request.metadata.get("trace_id"),
                },
            )

        # 默认异步：仅登记待审批请求，由 UI 弹窗决策后回写。
        if self.decision_provider is None:
            return False

        allowed = bool(self.decision_provider(artifact))
        self.decide(request_id, allowed)
        return allowed

    def get_pending(self, request_id: str | None = None) -> PendingConsent | None:
        if request_id is not None:
            return self.pending.get(request_id)
        if not self.pending:
            return None
        # 返回最近一个未决策请求
        for item in reversed(list(self.pending.values())):
            if not item.decided:
                return item
        return None

    def decide(self, request_id: str, allowed: bool) -> dict[str, Any]:
        pending = self.pending.get(request_id)
        if pending is None:
            raise KeyError(f"unknown consent request_id: {request_id}")
        decision = "allow" if allowed else "deny"
        artifact = dict(pending.artifact)
        artifact["user_decision"] = decision
        artifact["allowed"] = allowed
        artifact["timestamp"] = time.time()
        pending.artifact = artifact
        pending.decided = True
        pending.allowed = allowed
        self.last_artifact = artifact
        if self.event_stream is not None:
            self.event_stream.append(
                "consent/decided",
                {
                    "request_id": request_id,
                    "plan_id": pending.consent_request.plan_id,
                    "step_id": pending.consent_request.step_id,
                    "allowed": allowed,
                    "decision": decision,
                    "trace_id": pending.consent_request.metadata.get("trace_id"),
                },
            )
        if self.db_conn is not None:
            self.db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consent_artifacts(
                    request_id TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            persist_consent_artifact(self.db_conn, artifact)
        return artifact

    def to_modal_payload(self, request_id: str | None = None) -> dict[str, Any]:
        pending = self.get_pending(request_id)
        if pending is None:
            return {
                "title": "出站同意",
                "body": "当前没有待审批请求。",
                "purpose_type": PurposeType.NATIVE_RISK_PROMPT.value,
            }
        req = pending.consent_request
        body = (
            f"计划: {req.plan_id}\n"
            f"步骤: {req.step_id}\n"
            f"技能: {req.skill_id}\n"
            f"操作: {req.operation}\n"
            f"风险等级: {req.risk_level}\n"
            f"影响范围: {req.impact_scope}"
        )
        return {
            "title": "任务步骤需要审批",
            "body": body,
            "purpose_type": pending.artifact.get("purpose"),
            "request_id": pending.request_id,
            "plan_id": req.plan_id,
            "step_id": req.step_id,
            "skill_id": req.skill_id,
            "risk_level": req.risk_level,
            "status": "decided" if pending.decided else "pending",
            "allowed": pending.allowed if pending.decided else None,
        }
