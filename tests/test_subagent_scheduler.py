from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from offline_companion.core.plan_orchestrator import (
    InMemoryPlanStore,
    PlanContext,
    PlanOrchestrator,
    PlanStatus,
    PlanStep,
    StepStatus,
)
from offline_companion.core.subagent_scheduler import RestrictedToolRegistry, SubagentScheduler
from offline_companion.core.subagent_types import SubagentContext, SubagentRouterResponse


class SpySubagentScheduler(SubagentScheduler):
    """摘要：记录 spawn/run 调用的测试调度器。"""

    def __init__(self) -> None:
        super().__init__()
        self.spawned: list[SubagentContext] = []
        self.run_count = 0

    def spawn(self, **kwargs) -> SubagentContext:
        context = super().spawn(**kwargs)
        self.spawned.append(context)
        return context

    def run(self, ctx: SubagentContext):
        self.run_count += 1
        return super().run(ctx)


class MockRouter:
    """摘要：按预设响应队列返回子 Agent LLM 响应。"""

    def __init__(self, responses: list[SubagentRouterResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[dict[str, object]] = []

    def route(self, *, messages, system_prompt, privacy_mode, tools=None) -> SubagentRouterResponse:
        self._call_count += 1
        self.calls.append(
            {
                "messages": list(messages),
                "system_prompt": system_prompt,
                "privacy_mode": privacy_mode,
                "tools": tools,
            }
        )
        if self._call_count <= len(self._responses):
            return self._responses[self._call_count - 1]
        return SubagentRouterResponse(content="", tool_calls=[], finish_reason="stop")


class MockConsentGateway:
    """摘要：记录命令审批调用的测试网关。"""

    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.checked: list[dict[str, object]] = []

    def check(self, *, tool_name, arguments, session_id) -> dict[str, object]:
        self.checked.append(
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": session_id,
            }
        )
        return {"allowed": self.allowed, "consent_request_id": None if self.allowed else "cr-1"}


class SubmitConsentGateway:
    """摘要：仅提供 submit() 的测试审批网关。"""

    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.requests: list[object] = []
        self.last_artifact = {"request_id": "submit-cr-1"}

    def submit(self, request) -> bool:
        """摘要：记录 ConsentRequest 并返回预设审批结果。"""
        self.requests.append(request)
        return self.allowed


def test_spawn_creates_context_with_independent_messages() -> None:
    scheduler = SubagentScheduler()

    context = scheduler.spawn(
        parent_session_id="parent",
        role="implementer",
        task_description="实现排序函数",
        allowed_files=["src/sort.py"],
    )

    assert context.subagent_id.startswith("sub_")
    assert context.parent_session_id == "parent"
    assert context.messages == []
    assert context.allowed_files == ["src/sort.py"]
    assert "实现排序函数" in context.system_prompt


def test_spawn_inherits_privacy_mode() -> None:
    scheduler = SubagentScheduler()

    context = scheduler.spawn(
        parent_session_id="parent",
        role="reviewer",
        task_description="审查 diff",
        allowed_files=[],
        privacy_mode="ask_before_cloud",
    )

    assert context.privacy_mode == "ask_before_cloud"
    assert context.role == "reviewer"


def test_run_stub_returns_completed() -> None:
    scheduler = SubagentScheduler()
    context = scheduler.spawn(
        parent_session_id="parent",
        role="implementer",
        task_description="实现功能",
        allowed_files=[],
    )

    result = scheduler.run(context)

    assert result.status == "completed"
    assert result.subagent_id == context.subagent_id
    assert "stub" in result.output
    assert result.evidence is not None


def test_planstep_subagent_type_default_none() -> None:
    step = PlanStep(step_id="s1", skill_id="chat", result_key="r1")

    assert step.subagent_type is None


def test_snapshot_serializes_subagent_type() -> None:
    step = PlanStep(
        step_id="s1",
        skill_id="chat",
        result_key="r1",
        subagent_type="implementer",
    )
    context = PlanContext(
        plan_id="p1",
        steps={"s1": step},
        step_status={"s1": StepStatus.PENDING},
    )

    restored = PlanContext.from_snapshot(context.to_snapshot())

    assert restored.steps["s1"].subagent_type == "implementer"


def test_legacy_snapshot_defaults_subagent_type_to_none() -> None:
    step = PlanStep(step_id="s1", skill_id="chat", result_key="r1")
    snapshot = PlanContext(
        plan_id="p1",
        steps={"s1": step},
        step_status={"s1": StepStatus.PENDING},
    ).to_snapshot()
    del snapshot["steps"]["s1"]["subagent_type"]

    restored = PlanContext.from_snapshot(snapshot)

    assert restored.steps["s1"].subagent_type is None


def test_execute_next_dispatches_to_subagent() -> None:
    scheduler = SpySubagentScheduler()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), subagent_scheduler=scheduler)
    step = PlanStep(
        step_id="s1",
        skill_id="chat",
        result_key="r1",
        title="实现功能",
        description="实现子 Agent 功能",
        files=("src/app.py",),
        subagent_type="implementer",
    )
    context = PlanContext(
        plan_id="p1",
        steps={"s1": step},
        step_status={"s1": StepStatus.PENDING},
        context_vars={"session_id": "parent-session", "privacy_mode": "local_only"},
    )

    result = orchestrator.execute_next(context)

    assert result.status is PlanStatus.DONE
    assert scheduler.run_count == 1
    assert scheduler.spawned[0].parent_session_id == "parent-session"
    assert scheduler.spawned[0].allowed_files == ["src/app.py"]
    assert scheduler.spawned[0].plan_id == "p1"
    assert scheduler.spawned[0].step_id == "s1"
    payload = result.get_step_result("s1")
    assert payload["subagent_id"] == scheduler.spawned[0].subagent_id
    assert payload["subagent_role"] == "implementer"


def test_execute_next_without_subagent_type_uses_existing_invoker() -> None:
    scheduler = SpySubagentScheduler()
    orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        skill_invoker=lambda skill_id, payload, idem: {"skill_id": skill_id, "payload": payload, "idem": idem},
        subagent_scheduler=scheduler,
    )
    step = PlanStep(step_id="s1", skill_id="chat", result_key="r1")
    context = PlanContext(
        plan_id="p1",
        steps={"s1": step},
        step_status={"s1": StepStatus.PENDING},
    )

    result = orchestrator.execute_next(context)

    assert result.status is PlanStatus.DONE
    assert scheduler.run_count == 0
    assert result.get_step_result("s1")["skill_id"] == "chat"


def test_build_system_prompt_contains_file_content(tmp_path: Path) -> None:
    code_file = tmp_path / "foo.py"
    code_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    scheduler = SubagentScheduler()

    prompt = scheduler._build_system_prompt("implementer", "implement hello module", [str(code_file)])

    assert "def hello():" in prompt
    assert "return 'world'" in prompt
    assert "## Allowed Files" in prompt
    assert "Isolation Discipline" in prompt


def test_build_system_prompt_truncates_large_file(tmp_path: Path) -> None:
    from offline_companion.core import subagent_scheduler as mod

    big_file = tmp_path / "big.py"
    big_file.write_text("x" * (mod._MAX_FILE_CHARS + 5000), encoding="utf-8")
    scheduler = SubagentScheduler()

    prompt = scheduler._build_system_prompt("implementer", "task", [str(big_file)])

    assert "[truncated" in prompt
    assert "x" * (mod._MAX_FILE_CHARS + 1) not in prompt


def test_build_system_prompt_handles_missing_file(tmp_path: Path) -> None:
    scheduler = SubagentScheduler()

    prompt = scheduler._build_system_prompt("implementer", "task", [str(tmp_path / "missing.py")])

    assert "[file not found]" in prompt


def test_build_system_prompt_reviewer_role_instruction() -> None:
    scheduler = SubagentScheduler()

    prompt = scheduler._build_system_prompt("reviewer", "task", [])

    assert "reviewer" in prompt.lower()
    assert "approved" in prompt


def test_validate_file_access_allows_allowed_file(tmp_path: Path) -> None:
    target = tmp_path / "safe.py"
    target.write_text("# safe", encoding="utf-8")

    assert SubagentScheduler.validate_file_access(str(target), [str(target)])


def test_validate_file_access_rejects_outside_and_empty_allowed(tmp_path: Path) -> None:
    allowed = tmp_path / "safe.py"
    allowed.write_text("# safe", encoding="utf-8")
    outside = tmp_path / "evil.py"
    outside.write_text("# evil", encoding="utf-8")

    assert not SubagentScheduler.validate_file_access(str(outside), [str(allowed)])
    assert not SubagentScheduler.validate_file_access(str(outside), [])


def test_validate_file_access_rejects_path_traversal(tmp_path: Path) -> None:
    safe = tmp_path / "safe.py"
    safe.write_text("# safe", encoding="utf-8")
    evil = str(safe / ".." / ".." / ".." / "etc" / "passwd")

    assert not SubagentScheduler.validate_file_access(evil, [str(safe)])


@dataclass
class _StubManifest:
    tool_id: str


class _StubRegistry:
    """摘要：测试用底层工具注册表。"""

    def __init__(self) -> None:
        self.invoked: list[tuple[str, dict[str, object]]] = []

    def list_available(self) -> list[dict[str, str]]:
        return [
            {"name": "file_read"},
            {"name": "file_write"},
            {"name": "execute_command"},
            {"name": "dangerous_tool"},
        ]

    def get_tool(self, name: str) -> dict[str, str] | None:
        if name in {"file_read", "file_write", "execute_command", "dangerous_tool"}:
            return {"name": name}
        return None

    def invoke(self, name: str, arguments: dict[str, object], context=None) -> dict[str, object]:
        del context
        self.invoked.append((name, arguments))
        return {"ok": True, "tool": name}


class _ManifestRegistry:
    """摘要：模拟现有 ToolRegistry 的 manifest 形状。"""

    def list_available(self) -> list[_StubManifest]:
        return [_StubManifest("file_read"), _StubManifest("dangerous_tool")]

    def get_manifest(self, name: str) -> _StubManifest | None:
        return _StubManifest(name)


def test_restricted_registry_filters_tools() -> None:
    reg = RestrictedToolRegistry(base=_StubRegistry(), allowed_files=[])

    names = {tool["name"] for tool in reg.list_available()}

    assert names == {"file_read", "file_write", "execute_command"}


def test_restricted_registry_filters_manifest_tools() -> None:
    reg = RestrictedToolRegistry(base=_ManifestRegistry(), allowed_files=[])

    names = {tool.tool_id for tool in reg.list_available()}

    assert names == {"file_read"}


def test_restricted_registry_blocks_file_outside_allowed(tmp_path: Path) -> None:
    allowed = tmp_path / "safe.py"
    allowed.write_text("# safe", encoding="utf-8")
    outside = tmp_path / "evil.py"
    outside.write_text("# evil", encoding="utf-8")
    stub = _StubRegistry()
    reg = RestrictedToolRegistry(base=stub, allowed_files=[str(allowed)])

    result = reg.invoke("file_read", {"path": str(outside)})

    assert "error" in result
    assert "file access denied" in str(result["error"])
    assert stub.invoked == []


def test_restricted_registry_allows_file_in_allowed(tmp_path: Path) -> None:
    target = tmp_path / "safe.py"
    target.write_text("# safe", encoding="utf-8")
    stub = _StubRegistry()
    reg = RestrictedToolRegistry(base=stub, allowed_files=[str(target)])

    result = reg.invoke("file_read", {"path": str(target)})

    assert result == {"ok": True, "tool": "file_read"}
    assert stub.invoked == [("file_read", {"path": str(target)})]


def test_restricted_registry_rejects_non_whitelisted_tool() -> None:
    stub = _StubRegistry()
    reg = RestrictedToolRegistry(base=stub, allowed_files=[])

    result = reg.invoke("dangerous_tool", {})

    assert "error" in result
    assert stub.invoked == []


def test_run_calls_tool_factory_and_stores_in_ctx() -> None:
    sentinel = object()
    factory_called = False

    def factory(ctx: SubagentContext) -> object:
        nonlocal factory_called
        factory_called = True
        assert ctx.messages == []
        return sentinel

    scheduler = SubagentScheduler(tool_registry_factory=factory)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
    )

    result = scheduler.run(ctx)

    assert factory_called
    assert ctx.tool_registry is sentinel
    assert result.status == "completed"


def test_run_without_factory_leaves_tool_registry_none() -> None:
    scheduler = SubagentScheduler()
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
    )

    result = scheduler.run(ctx)

    assert ctx.tool_registry is None
    assert result.status == "completed"


def test_run_completes_within_budget() -> None:
    router = MockRouter([SubagentRouterResponse(content="Task done", tool_calls=[], finish_reason="stop")])
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
    )

    result = scheduler.run(ctx)

    assert result.status == "completed"
    assert result.output == "Task done"
    assert "1 LLM calls" in str(result.evidence)
    assert router._call_count == 1


def test_run_exhausts_budget_returns_timeout() -> None:
    tool_call = [{"id": "tc-1", "name": "file_read", "arguments": {}}]
    router = MockRouter(
        [
            SubagentRouterResponse(content="", tool_calls=tool_call, finish_reason="tool_calls"),
            SubagentRouterResponse(content="", tool_calls=tool_call, finish_reason="tool_calls"),
            SubagentRouterResponse(content="", tool_calls=tool_call, finish_reason="tool_calls"),
            SubagentRouterResponse(content="", tool_calls=tool_call, finish_reason="tool_calls"),
        ]
    )
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
        max_llm_calls=3,
    )

    result = scheduler.run(ctx)

    assert result.status == "timeout"
    assert result.error == "max_llm_calls exceeded"
    assert router._call_count == 3


def test_run_completes_after_tool_calls() -> None:
    router = MockRouter(
        [
            SubagentRouterResponse(
                content="",
                tool_calls=[{"id": "tc-1", "name": "file_read", "arguments": {"path": "/dev/null"}}],
                finish_reason="tool_calls",
            ),
            SubagentRouterResponse(content="Done after reading", tool_calls=[], finish_reason="stop"),
        ]
    )
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
    )

    result = scheduler.run(ctx)

    assert result.status == "completed"
    assert result.output == "Done after reading"
    assert router._call_count == 2
    assert [message["role"] for message in ctx.messages] == ["system", "user", "assistant", "tool", "assistant"]


def test_run_llm_error_returns_failed() -> None:
    class FailingRouter:
        def route(self, **kwargs):
            del kwargs
            raise RuntimeError("LLM unavailable")

    scheduler = SubagentScheduler(auto_router=FailingRouter())
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
    )

    result = scheduler.run(ctx)

    assert result.status == "failed"
    assert "LLM route error" in str(result.error)


def test_reviewer_cannot_write_file_or_execute_command() -> None:
    reg = RestrictedToolRegistry(base=_StubRegistry(), allowed_files=[], role="reviewer")

    names = {tool["name"] for tool in reg.list_available()}
    write_result = reg.invoke("file_write", {"path": "/tmp/x"})
    command_result = reg.invoke("execute_command", {"command": "ls"})

    assert names == {"file_read"}
    assert "error" in write_result
    assert "error" in command_result


def test_implementer_can_write_file(tmp_path: Path) -> None:
    target = tmp_path / "safe.py"
    target.write_text("# safe", encoding="utf-8")
    reg = RestrictedToolRegistry(base=_StubRegistry(), allowed_files=[str(target)], role="implementer")

    result = reg.invoke("file_write", {"path": str(target)})

    assert result["ok"] is True
    assert result["tool"] == "file_write"


def test_execute_command_blocked_without_consent() -> None:
    gateway = MockConsentGateway(allowed=False)
    reg = RestrictedToolRegistry(
        base=_StubRegistry(),
        allowed_files=[],
        role="implementer",
        consent_gateway=gateway,
    )

    result = reg.invoke("execute_command", {"command": "rm -rf /"}, {"session_id": "sess-1"})

    assert "error" in result
    assert "denied by consent" in str(result["error"])
    assert result["consent_request_id"] == "cr-1"
    assert gateway.checked[0]["session_id"] == "sess-1"


def test_execute_command_allowed_with_consent() -> None:
    gateway = MockConsentGateway(allowed=True)
    reg = RestrictedToolRegistry(
        base=_StubRegistry(),
        allowed_files=[],
        role="implementer",
        consent_gateway=gateway,
    )

    result = reg.invoke("execute_command", {"command": "ls"}, {"session_id": "sess-1"})

    assert result["ok"] is True
    assert result["tool"] == "execute_command"
    assert len(gateway.checked) == 1


def test_run_stops_on_interrupt_before_loop() -> None:
    router = MockRouter([])
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
    )
    ctx.interrupted = True

    result = scheduler.run(ctx)

    assert result.status == "failed"
    assert result.error == "interrupted"
    assert router._call_count == 0


def test_run_stops_after_tool_call_on_interrupt() -> None:
    router = MockRouter(
        [
            SubagentRouterResponse(
                content="",
                tool_calls=[{"id": "tc-1", "name": "file_read", "arguments": {}}],
                finish_reason="tool_calls",
            )
        ]
    )
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
        max_llm_calls=5,
    )
    original_exec = scheduler._execute_tool_call

    def spy_exec(current_ctx, tool_call):
        result = original_exec(current_ctx, tool_call)
        current_ctx.interrupted = True
        return result

    scheduler._execute_tool_call = spy_exec

    result = scheduler.run(ctx)

    assert result.status == "failed"
    assert result.error == "interrupted"
    assert router._call_count == 1


def test_router_receives_privacy_mode() -> None:
    router = MockRouter([SubagentRouterResponse(content="done", tool_calls=[], finish_reason="stop")])
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
        privacy_mode="ask_before_cloud",
    )

    scheduler.run(ctx)

    assert router.calls[0]["privacy_mode"] == "ask_before_cloud"


def test_tool_call_context_carries_privacy_mode() -> None:
    router = MockRouter(
        [
            SubagentRouterResponse(
                content="",
                tool_calls=[{"id": "tc-1", "name": "file_read", "arguments": {}}],
                finish_reason="tool_calls",
            ),
            SubagentRouterResponse(content="done", tool_calls=[], finish_reason="stop"),
        ]
    )
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
        privacy_mode="ask_before_cloud",
    )
    captured_context: dict[str, object] = {}

    class SpyRegistry:
        def list_available(self):
            return [{"name": "file_read"}]

        def invoke(self, name, args, context=None):
            del name, args
            captured_context.update(context or {})
            return {"ok": True}

    ctx.tool_registry = SpyRegistry()

    scheduler.run(ctx)

    assert captured_context["privacy_mode"] == "ask_before_cloud"
    assert captured_context["session_id"] == "sess-1"


def test_get_tool_schemas_from_registry() -> None:
    reg = RestrictedToolRegistry(base=_StubRegistry(), allowed_files=[], role="implementer")
    scheduler = SubagentScheduler()
    ctx = SubagentContext(
        subagent_id="sub-1",
        parent_session_id="s1",
        role="implementer",
        task_description="t",
        allowed_files=[],
        system_prompt="",
        tool_registry=reg,
    )

    schemas = scheduler._get_tool_schemas(ctx)

    assert schemas is not None
    assert {item["function"]["name"] for item in schemas} == {"file_read", "file_write", "execute_command"}


class _ObjectReturnRegistry:
    """摘要：模拟 base.invoke 返回普通对象的底层工具。"""

    class Result:
        """摘要：测试用对象返回值。"""

        def __init__(self, ok: bool, tool: str) -> None:
            self.ok = ok
            self.tool = tool

    def list_available(self):
        """摘要：返回文件读取工具。"""
        return [{"name": "file_read"}]

    def invoke(self, name, args, context=None):
        """摘要：返回非 dict 对象。"""
        del args, context
        return self.Result(ok=True, tool=name)


def test_invoke_normalizes_object_return(tmp_path: Path) -> None:
    """摘要：base.invoke 返回对象时，RestrictedToolRegistry 归一化为 dict。"""
    target = tmp_path / "safe.py"
    target.write_text("# safe", encoding="utf-8")
    reg = RestrictedToolRegistry(
        base=_ObjectReturnRegistry(),
        allowed_files=[str(target)],
        role="implementer",
    )

    result = reg.invoke("file_read", {"path": str(target)})

    assert result["ok"] is True
    assert result["tool"] == "file_read"


def test_spawn_carries_plan_and_step_id() -> None:
    """摘要：spawn() 将 plan_id/step_id 写入 SubagentContext。"""
    scheduler = SubagentScheduler()

    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
        plan_id="plan-42",
        step_id="step-7",
    )

    assert ctx.plan_id == "plan-42"
    assert ctx.step_id == "step-7"


def test_execute_command_submit_consent_uses_plan_and_step_id() -> None:
    """摘要：submit 审批路径使用子 Agent 上下文中的 plan_id/step_id。"""
    gateway = SubmitConsentGateway(allowed=False)
    reg = RestrictedToolRegistry(
        base=_StubRegistry(),
        allowed_files=[],
        role="implementer",
        consent_gateway=gateway,
    )

    result = reg.invoke(
        "execute_command",
        {"command": "dir"},
        {
            "session_id": "sess-1",
            "plan_id": "plan-42",
            "step_id": "step-7",
        },
    )

    assert "error" in result
    assert result["consent_request_id"] == "submit-cr-1"
    assert len(gateway.requests) == 1
    assert gateway.requests[0].plan_id == "plan-42"
    assert gateway.requests[0].step_id == "step-7"


def test_tool_call_context_includes_plan_and_step_id() -> None:
    """摘要：_execute_tool_call 透传 plan_id/step_id 到工具上下文。"""
    router = MockRouter(
        [
            SubagentRouterResponse(
                content="",
                tool_calls=[{"id": "tc-1", "name": "file_read", "arguments": {}}],
                finish_reason="tool_calls",
            ),
            SubagentRouterResponse(content="done", tool_calls=[], finish_reason="stop"),
        ]
    )
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(
        parent_session_id="sess-1",
        role="implementer",
        task_description="test",
        allowed_files=[],
        plan_id="plan-42",
        step_id="step-7",
    )
    captured_context: dict[str, object] = {}

    class SpyRegistry:
        """摘要：记录工具调用上下文。"""

        def list_available(self):
            """摘要：返回文件读取工具。"""
            return [{"name": "file_read"}]

        def invoke(self, name, args, context=None):
            """摘要：捕获工具调用上下文。"""
            del name, args
            captured_context.update(context or {})
            return {"ok": True}

    ctx.tool_registry = SpyRegistry()

    scheduler.run(ctx)

    assert captured_context["plan_id"] == "plan-42"
    assert captured_context["step_id"] == "step-7"


def test_reviewer_parses_approved_json_output() -> None:
    """摘要：reviewer 返回合规 JSON 时填充审查字段。"""
    review_json = json.dumps({"approved": True, "issues": [], "suggestions": ["补充 docstring"]})
    router = MockRouter([SubagentRouterResponse(content=review_json, tool_calls=[], finish_reason="stop")])
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(parent_session_id="sess-1", role="reviewer", task_description="review", allowed_files=[])

    result = scheduler.run(ctx)

    assert result.status == "completed"
    assert result.approved is True
    assert result.issues == []
    assert result.suggestions == ["补充 docstring"]
    assert "approved=True" in str(result.evidence)


def test_reviewer_parses_markdown_wrapped_json() -> None:
    """摘要：reviewer 返回 Markdown JSON 代码块时正确解析。"""
    review_content = "```json\n" + json.dumps(
        {"approved": False, "issues": ["缺少错误处理"], "suggestions": []},
        ensure_ascii=False,
    ) + "\n```"
    router = MockRouter([SubagentRouterResponse(content=review_content, tool_calls=[], finish_reason="stop")])
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(parent_session_id="sess-1", role="reviewer", task_description="review", allowed_files=[])

    result = scheduler.run(ctx)

    assert result.approved is False
    assert result.issues == ["缺少错误处理"]
    assert result.suggestions == []


def test_reviewer_parse_failure_sets_approved_false() -> None:
    """摘要：reviewer 返回非 JSON 时默认不通过并记录格式问题。"""
    router = MockRouter([SubagentRouterResponse(content="looks fine", tool_calls=[], finish_reason="stop")])
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(parent_session_id="sess-1", role="reviewer", task_description="review", allowed_files=[])

    result = scheduler.run(ctx)

    assert result.status == "completed"
    assert result.approved is False
    assert result.issues is not None
    assert any("format error" in item for item in result.issues)


def test_implementer_does_not_parse_reviewer_output() -> None:
    """摘要：implementer 不解析 reviewer 协议字段。"""
    router = MockRouter([SubagentRouterResponse(content='{"approved": true}', tool_calls=[], finish_reason="stop")])
    scheduler = SubagentScheduler(auto_router=router)
    ctx = scheduler.spawn(parent_session_id="sess-1", role="implementer", task_description="implement", allowed_files=[])

    result = scheduler.run(ctx)

    assert result.status == "completed"
    assert result.approved is None
    assert result.issues is None
    assert result.suggestions is None


class _GenerateBackend:
    """摘要：测试用本地 generate 后端。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs) -> str:
        """摘要：记录调用并返回固定文本。"""
        self.calls.append(dict(kwargs))
        return "adapter reply"


def test_subagent_router_adapter_uses_local_backend_generate() -> None:
    """摘要：生产 adapter 通过本地 backend.generate() 生成子 Agent 回复。"""
    from offline_companion.shell.ui_host.bootstrap import _SubagentRouterAdapter

    backend = _GenerateBackend()
    adapter = _SubagentRouterAdapter(backend, max_tokens=123)

    result = adapter.route(
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "do task"}],
        system_prompt="sys",
        privacy_mode="local_only",
        tools=[{"type": "function", "function": {"name": "file_read"}}],
    )

    assert result.content == "adapter reply"
    assert result.tool_calls == []
    assert backend.calls[0]["system_prompt"] == "sys"
    assert "do task" in str(backend.calls[0]["user_message"])
    assert backend.calls[0]["memory_block"] == ""
    assert backend.calls[0]["max_tokens"] == 123


def test_subagent_router_adapter_returns_error_without_generate() -> None:
    """摘要：backend 无 generate() 时 adapter fail-safe 返回 error。"""
    from offline_companion.shell.ui_host.bootstrap import _SubagentRouterAdapter

    result = _SubagentRouterAdapter(object()).route(
        messages=[],
        system_prompt="sys",
        privacy_mode="local_only",
    )

    assert result.finish_reason == "error"
    assert result.content == ""
