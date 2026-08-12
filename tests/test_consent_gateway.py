from __future__ import annotations

import sqlite3
from pathlib import Path

from offline_companion.core.plan_orchestrator import ConsentRequest, PlanOrchestrator
from offline_companion.shell.outbound_manager.a3_gateway import (
    UIHostConsentGateway,
    build_consent_artifact,
)


def test_a3_gateway_builds_and_decides_artifact(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "consent.db")
    gateway = UIHostConsentGateway(db_conn=conn, decision_provider=lambda artifact: True)
    request = ConsentRequest(plan_id="p1", step_id="s1", skill_id="skill_cloud_x", operation="execute_step", risk_level="high")

    allowed = gateway.submit(request)

    assert allowed is True
    assert gateway.last_artifact is not None
    assert gateway.last_artifact["user_decision"] == "allow"
    assert gateway.last_artifact["purpose"] in {"skill_cloud_inference", "plugin_high_risk_skill", "native_risk_prompt"}


def test_a3_gateway_modal_payload_reflects_pending_request() -> None:
    gateway = UIHostConsentGateway()
    request = ConsentRequest(plan_id="p2", step_id="s2", skill_id="skill_network_x", operation="execute_step")
    gateway.submit(request)

    payload = gateway.to_modal_payload()

    assert payload["plan_id"] == "p2"
    assert payload["step_id"] == "s2"
    assert payload["status"] == "pending"
    assert payload["purpose_type"] == "skill_network_egress"


def test_build_artifact_uses_accepted_schema() -> None:
    request = ConsentRequest(plan_id="p3", step_id="s3", skill_id="skill_file_x", operation="execute_step")
    artifact = build_consent_artifact(request, user_decision="pending", request_id="rid-1")

    assert artifact["request_id"] == "rid-1"
    assert artifact["scope"] == "this_turn"
    assert artifact["purpose"] == "skill_file_access"
    assert artifact["user_decision"] == "pending"
    assert artifact["data_category"] == "plan_step"


def test_top_level_purpose_type_overrides_metadata() -> None:
    request = ConsentRequest(
        plan_id="p3",
        step_id="s3",
        skill_id="skill_cloud_x",
        operation="execute_step",
        purpose_type="skill_file_access",
        metadata={"purpose_type": "skill_cloud_inference"},
    )
    artifact = build_consent_artifact(request, user_decision="pending", request_id="rid-2")

    assert artifact["purpose"] == "skill_file_access"


def test_desktop_bridge_returns_gateway_payload(tmp_path: Path) -> None:
    gateway = UIHostConsentGateway()
    request = ConsentRequest(plan_id="p4", step_id="s4", skill_id="skill_cloud_x", operation="execute_step")
    gateway.submit(request)

    orchestrator = PlanOrchestrator(store=tmp_path / "state.db", consent_gateway=gateway)
    assert orchestrator.consent_gateway is gateway
