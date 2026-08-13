from __future__ import annotations

import sqlite3

from offline_companion.core.hard_gate import HardGate
from offline_companion.core.plan_orchestrator import (
    A3ConsentAdapter,
    InMemoryPlanStore,
    PlanOrchestrator,
    PlanStatus,
)
from offline_companion.core.skill_execution_tracker import SkillExecutionTracker
from offline_companion.shared.messages import BaseMessage
from offline_companion.shell.auto_router import AutoRouter, RoutingContext
from offline_companion.shell.auto_turn_orchestrator import (
    AutoTurnOrchestrator,
    ConversationPlanInvoker,
    auto_turn_to_payload,
)
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.plan_auto_bridge import PlanAutoBridge


def test_auto_turn_executes_decided_steps() -> None:
    plan_orchestrator = PlanOrchestrator(InMemoryPlanStore())
    bridge = PlanAutoBridge(
        AutoRouter(),
        plan_orchestrator,
        lambda message: RoutingContext(query=message.topic, privacy_mode="local_only"),
    )
    auto_turn = AutoTurnOrchestrator(
        plan_orchestrator=plan_orchestrator,
        auto_bridge=bridge,
        invoke_skill=lambda step, context: {"result": step.payload["description"]},
    )

    context = auto_turn.execute_turn(
        BaseMessage(message_id="m-1", topic="chat.auto", source="shell"),
        "分析当前模块",
    )
    payload = auto_turn_to_payload(context)

    assert context.status is PlanStatus.DONE
    assert len(context.step_results) == 3
    assert payload["route_mode"] == "auto"
    assert payload["reply"]


def test_conversation_plan_invoker_passes_local_profile() -> None:
    profile = object()
    captured = {}

    class SessionCore:
        def assemble_reply(self, *args, **kwargs):
            captured.update(kwargs)
            return type("Result", (), {"reply": "ok"})()

    orchestrator = type(
        "Orchestrator",
        (),
        {
            "session_core": SessionCore(),
            "backend": object(),
            "conn": object(),
            "max_tokens": 128,
            "_local_capability_profile": lambda self: profile,
        },
    )()

    result = ConversationPlanInvoker(orchestrator).invoke(
        "chat",
        {"query": "goal", "description": "step"},
    )

    assert result["result"] == "ok"
    assert captured["capability_profile"] is profile


def _streaming_auto_turn(*, gateway=None):
    plan_orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        consent_adapter=A3ConsentAdapter(gateway) if gateway else None,
        consent_gateway=gateway,
    )
    bridge = PlanAutoBridge(
        AutoRouter(),
        plan_orchestrator,
        lambda message: RoutingContext(query=message.topic, privacy_mode="local_only"),
    )
    return AutoTurnOrchestrator(
        plan_orchestrator=plan_orchestrator,
        auto_bridge=bridge,
        invoke_skill=_stage_aware_result,
    )


def _stage_aware_result(step, context):
    """摘要：按阶段返回满足后置校验的测试产出。"""
    if step.stage == "planning":
        return {"result": f"{step.payload['description']}；涉及 plan_orchestrator 模块、数据流和风险。"}
    if step.stage == "tdd":
        return {"result": f"{step.payload['description']}；测试 passed。"}
    if step.stage == "implementation":
        return {"result": f"{step.payload['description']}；修改 src/app.py。"}
    if step.stage == "verification":
        return {"result": f"{step.payload['description']}；验证 output ok。"}
    return {"result": step.payload["description"]}


def test_auto_turn_stream_emits_step_sequence() -> None:
    auto_turn = _streaming_auto_turn()

    events = list(
        auto_turn.execute_turn_stream(
            BaseMessage(message_id="m-1", topic="chat.auto", source="shell"),
            "分析当前模块",
        )
    )

    assert events[0]["type"] == "plan_start"
    assert [event["type"] for event in events].count("step_start") == 3
    assert [event["type"] for event in events].count("step_complete") == 3
    assert events[-1]["type"] == "plan_complete"
    assert events[-1]["done"] is True
    first_start = next(event for event in events if event["type"] == "step_start")
    assert first_start["title"]
    assert first_start["description"]
    assert first_start["expected_output"]
    assert first_start["verification"]
    assert "completion_criteria" in first_start
    assert "stage" in first_start
    first_complete = next(event for event in events if event["type"] == "step_complete")
    assert first_complete["status"] == "completed"
    assert first_complete["evidence"]


def test_auto_turn_stream_consent_resume_and_deny() -> None:
    gateway = UIHostConsentGateway()
    auto_turn = _streaming_auto_turn(gateway=gateway)
    message = BaseMessage(message_id="m-1", topic="chat.auto", source="shell")
    initial = list(auto_turn.execute_turn_stream(message, "部署服务并配置网络权限"))
    consent_event = initial[-1]
    assert consent_event["type"] == "consent_required"
    request_id = consent_event["consent_request_id"]
    plan_id = consent_event["plan_id"]

    gateway.decide(request_id, True)
    resumed = list(
        auto_turn.execute_turn_stream(
            message,
            "",
            plan_id=plan_id,
            resume=True,
            consent_request_id=request_id,
        )
    )
    assert resumed[-1]["type"] == "plan_complete"

    deny_gateway = UIHostConsentGateway()
    deny_turn = _streaming_auto_turn(gateway=deny_gateway)
    denied_initial = list(deny_turn.execute_turn_stream(message, "部署服务并配置网络权限"))
    denied_event = denied_initial[-1]
    deny_gateway.decide(denied_event["consent_request_id"], False)
    denied = list(
        deny_turn.execute_turn_stream(
            message,
            "",
            plan_id=denied_event["plan_id"],
            resume=True,
            consent_request_id=denied_event["consent_request_id"],
        )
    )
    assert denied[-1]["type"] == "plan_cancelled"


def test_auto_turn_stream_emits_plan_blocked_on_hard_gate(tmp_path) -> None:
    class PlanningOnlyBackend:
        def chat(self, **_kwargs):
            return """[
                {
                    "title": "拆解实现步骤",
                    "description": "跳过 brainstorming 直接进入 planning。",
                    "expected_output": "计划步骤清单。",
                    "verification": "检查步骤都有验证方式。",
                    "completion_criteria": "计划可执行。",
                    "stage": "planning",
                    "estimated_minutes": 5,
                    "files": []
                }
            ]"""

    tracker = SkillExecutionTracker(sqlite3.connect(tmp_path / "blocked.db"))
    plan_orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        llm_backend=PlanningOnlyBackend(),
        hard_gate=HardGate(tracker),
        skill_tracker=tracker,
        skill_resolver=lambda _text: ("coding-agent", ["brainstorming", "planning", "tdd", "review", "finalize"]),
    )
    bridge = PlanAutoBridge(
        AutoRouter(),
        plan_orchestrator,
        lambda message: RoutingContext(query=message.topic, privacy_mode="local_only"),
    )
    auto_turn = AutoTurnOrchestrator(
        plan_orchestrator=plan_orchestrator,
        auto_bridge=bridge,
        invoke_skill=lambda step, context: {"result": step.title},
    )

    events = list(
        auto_turn.execute_turn_stream(
            BaseMessage(message_id="m-1", topic="chat.auto", source="shell", session_id="sess1"),
            "请写代码",
        )
    )

    blocked = [event for event in events if event["type"] == "plan_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["missing_stages"] == ["brainstorming"]
    assert blocked[0]["blocked_step_id"] == "step_0"
    assert blocked[0]["done"] is True
    assert all(event["type"] != "step_start" for event in events[events.index(blocked[0]) + 1 :])
