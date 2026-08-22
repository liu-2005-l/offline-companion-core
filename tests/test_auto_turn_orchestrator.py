from __future__ import annotations

import sqlite3

from offline_companion.core.decomposition_result import NotDecomposableResult
from offline_companion.core.hard_gate import HardGate
from offline_companion.core.plan_orchestrator import (
    A3ConsentAdapter,
    InMemoryPlanStore,
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
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
    plan_orchestrator.decide = lambda _text: [
        PlanStep("read", "chat", "read_result", payload={"description": "读取配置"}),
        PlanStep("report", "chat", "report_result", payload={"description": "生成报告"}),
    ]
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
    assert len(context.step_results) == 2
    assert payload["route_mode"] == "auto"
    assert payload["reply"] == "读取配置\n\n生成报告"


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


def test_conversation_plan_invoker_includes_stage_contract_and_retry_feedback() -> None:
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
            "_local_capability_profile": lambda self: object(),
        },
    )()

    ConversationPlanInvoker(orchestrator).invoke(
        "chat",
        {
            "query": "整理模块",
            "description": "形成规划方案",
            "stage": "planning",
            "_quality_retry_feedback": "上一次缺少模块说明",
        },
    )

    prompt = captured["user_message"]
    assert "当前阶段：planning" in prompt
    assert "验收证据字段：modules, data_flow" in prompt
    assert "质量校验反馈：\n上一次缺少模块说明" in prompt


def test_conversation_plan_invoker_executes_booth_tool_without_llm() -> None:
    captured = {}
    orchestrator = type(
        "StubConversationOrchestrator",
        (),
        {"backend": object(), "session_core": object()},
    )()

    result = ConversationPlanInvoker(orchestrator).invoke(
        "algorithm_booth",
        {"tool_args": {"multiplicand": 7, "multiplier": 3}},
    )

    assert result["result"].startswith("Booth 算法：7 x 3 = 21")
    assert result["algorithm_trace"]["result"] == 21
    assert captured == {}


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


def test_auto_turn_not_decomposable_event_keeps_fallback_notice() -> None:
    auto_turn = _streaming_auto_turn()
    auto_turn.plan_orchestrator.decide = lambda _text: NotDecomposableResult(
        reason="method_constraint_lost",
        original_input="按Booth算法计算7乘3",
        fallback_notice="无法按指定方法分步执行，已转为直接回答。",
    )

    events = list(
        auto_turn.execute_turn_stream(
            BaseMessage(message_id="m-fallback", topic="chat.auto", source="shell"),
            "按Booth算法计算7乘3",
        )
    )

    assert events == [
        {
            "type": "not_decomposable",
            "status": "not_decomposable",
            "reason": "method_constraint_lost",
            "fallback_notice": "无法按指定方法分步执行，已转为直接回答。",
            "done": True,
        }
    ]


def test_auto_turn_stream_uses_shared_final_reply_summarizer() -> None:
    auto_turn = _streaming_auto_turn()
    prompts: list[str] = []
    auto_turn.final_reply_summarizer = lambda prompt: prompts.append(prompt) or "统一终态总结"

    events = list(
        auto_turn.execute_turn_stream(
            BaseMessage(message_id="m-summary", topic="chat.auto", source="shell"),
            "分析当前模块",
        )
    )

    assert events[-1]["type"] == "plan_complete"
    assert events[-1]["reply"] == "统一终态总结"
    assert len(prompts) == 1


def test_auto_turn_summary_failure_uses_deterministic_reply() -> None:
    auto_turn = _streaming_auto_turn()

    def fail_summary(_prompt: str) -> str:
        raise RuntimeError("local model unavailable")

    auto_turn.final_reply_summarizer = fail_summary

    events = list(
        auto_turn.execute_turn_stream(
            BaseMessage(message_id="m-summary-fallback", topic="chat.auto", source="shell"),
            "分析当前模块",
        )
    )

    assert events[-1]["type"] == "plan_complete"
    assert events[-1]["reply"].startswith("任务已完成，完成 ")
    assert "执行结果" in events[-1]["reply"]


def test_auto_turn_failed_event_includes_final_reply() -> None:
    auto_turn = _streaming_auto_turn()
    auto_turn.plan_orchestrator.decide = lambda _text: [
        PlanStep(
            "planning",
            "chat",
            "planning_result",
            payload={"description": "分析模块"},
            title="分析模块",
            stage="planning",
        )
    ]
    auto_turn.invoke_skill = lambda _step, _context: "无阶段证据"

    events = list(
        auto_turn.execute_turn_stream(
            BaseMessage(message_id="m-failed", topic="chat.auto", source="shell"),
            "分析当前模块",
        )
    )

    assert events[-1]["type"] == "plan_failed"
    assert events[-1]["reply"].startswith("任务执行失败")


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
    assert denied[-1]["reply"].startswith("任务已取消")


def test_auto_turn_stream_emits_plan_blocked_on_hard_gate(tmp_path) -> None:
    class PlanningOnlyBackend:
        def chat(self, **_kwargs):
            return """[
                {
                    "title": "拆解实现步骤",
                    "description": "为写代码任务跳过 brainstorming 直接进入 planning。",
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
    assert "reply" not in blocked[0]
    assert all(event["type"] != "step_start" for event in events[events.index(blocked[0]) + 1 :])
