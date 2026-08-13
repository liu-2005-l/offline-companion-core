from __future__ import annotations

from offline_companion.core.plan_enums import PlanErrorCode, PlanEventName, PlanStage


def test_plan_event_name_values_match_public_sse_contract() -> None:
    """摘要：Plan SSE 事件枚举值保持现有前后端契约。"""
    assert PlanEventName.PLAN_START.value == "plan_start"
    assert PlanEventName.STEP_COMPLETE.value == "step_complete"
    assert PlanEventName.PLAN_COMPLETED.value == "plan_completed"
    assert PlanEventName.STEP_BLOCKED.value == "step_blocked"
    assert PlanEventName.STEP_UNBLOCKED.value == "step_unblocked"
    assert PlanEventName.CONSENT_REQUIRED.value == "consent_required"
    assert PlanEventName.ERROR.value == "error"


def test_plan_stage_covers_existing_skill_and_generic_stages() -> None:
    """摘要：PlanStage 覆盖 coding-agent 五阶段和通用实现/验证阶段。"""
    existing = {
        "brainstorming",
        "planning",
        "tdd",
        "implementation",
        "review",
        "verification",
        "finalize",
    }
    assert {stage.value for stage in PlanStage} == existing


def test_plan_error_code_covers_existing_pause_and_error_reasons() -> None:
    """摘要：PlanErrorCode 覆盖当前计划链路持久化暂停原因与错误码。"""
    existing = {
        "decompose_failed",
        "dag_cycle",
        "hard_gate_blocked",
        "waiting_consent",
        "consent_denied",
        "step_timeout",
        "subagent_failed",
        "evidence_missing",
        "post_verification_failed",
    }
    assert {code.value for code in PlanErrorCode} >= existing
