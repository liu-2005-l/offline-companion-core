"""plan_enums：计划执行链路的事件名、阶段与错误码枚举。"""

from __future__ import annotations

from enum import Enum


class PlanEventName(str, Enum):
    """摘要：Auto/Plan SSE 对外事件名。"""

    ERROR = "error"
    PLAN_START = "plan_start"
    PLAN_COMPLETE = "plan_complete"
    PLAN_FAILED = "plan_failed"
    PLAN_CANCELLED = "plan_cancelled"
    PLAN_BLOCKED = "plan_blocked"
    PLAN_PAUSED = "plan_paused"
    STEP_START = "step_start"
    STEP_COMPLETE = "step_complete"
    STEP_FAILED = "step_failed"
    STEP_ERROR = "step_error"
    STEP_SKIPPED = "step_skipped"
    CONSENT_REQUIRED = "consent_required"


class PlanStage(str, Enum):
    """摘要：PlanStep 所属阶段；覆盖 coding-agent 五阶段与通用实现阶段。"""

    BRAINSTORMING = "brainstorming"
    PLANNING = "planning"
    TDD = "tdd"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    VERIFICATION = "verification"
    FINALIZE = "finalize"


class PlanErrorCode(str, Enum):
    """摘要：计划链路可持久化、可展示的错误码或暂停原因。"""

    DECOMPOSE_FAILED = "decompose_failed"
    DAG_CYCLE = "dag_cycle"
    HARD_GATE_BLOCKED = "hard_gate_blocked"
    WAITING_CONSENT = "waiting_consent"
    CONSENT_DENIED = "consent_denied"
    STEP_TIMEOUT = "step_timeout"
    SUBAGENT_FAILED = "subagent_failed"
    EVIDENCE_MISSING = "evidence_missing"
    POST_VERIFICATION_FAILED = "post_verification_failed"
