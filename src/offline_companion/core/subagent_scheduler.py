"""subagent_scheduler：子 Agent 调度器。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from offline_companion.core.subagent_types import (
    SubagentContext,
    SubagentResult,
    SubagentRole,
    SubagentRouterResponse,
)
from offline_companion.shared.types import PurposeType

_MAX_FILE_CHARS = 8000
_MAX_TOTAL_CHARS = 32000
_ROLE_TOOLS: dict[str, frozenset[str]] = {
    "implementer": frozenset({"file_read", "file_write", "execute_command"}),
    "reviewer": frozenset({"file_read"}),
}


class RestrictedToolRegistry:
    """摘要：子 Agent 受限工具注册表，限制工具子集与文件访问范围。"""

    def __init__(
        self,
        *,
        base: object,
        allowed_files: list[str],
        role: SubagentRole = "implementer",
        consent_gateway: object | None = None,
    ) -> None:
        """摘要：初始化受限工具注册表。

        参数：
            base: 底层工具对象，兼容 registry 或 invoker 的 duck typing。
            allowed_files: 子 Agent 可访问文件白名单。
            role: 子 Agent 角色，决定工具子集。
            consent_gateway: 用于 execute_command 的 A3 审批入口。
        """
        self._base = base
        self._allowed_files = list(allowed_files)
        self._role = role
        self._gateway = consent_gateway
        self._tools = _ROLE_TOOLS.get(role, frozenset())

    def list_available(self) -> list[Any]:
        """摘要：返回子 Agent 可见工具子集。"""
        base_list_method = getattr(self._base, "list_available", None)
        registry = getattr(self._base, "registry", None)
        if base_list_method is None and registry is not None:
            base_list_method = getattr(registry, "list_available", None)
        if base_list_method is None:
            return []
        return [
            tool
            for tool in (base_list_method() or [])
            if self._tool_name(tool) in self._tools
        ]

    def get_tool(self, name: str) -> object | None:
        """摘要：按名称获取白名单工具；非白名单返回 None。"""
        if name not in self._tools:
            return None
        getter = getattr(self._base, "get_tool", None)
        if getter is None:
            getter = getattr(getattr(self._base, "registry", None), "get_manifest", None)
        if getter is None:
            return None
        return getter(name)

    def invoke(self, name: str, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """摘要：调用白名单工具；文件读写先校验 allowed_files。"""
        if name not in self._tools:
            return {"error": f"tool '{name}' not available to {self._role} subagent"}
        if name in {"file_read", "file_write"}:
            path = str(arguments.get("path") or arguments.get("file_path") or "")
            if not SubagentScheduler.validate_file_access(path, self._allowed_files):
                return {"error": f"file access denied: '{path}' not in allowed_files"}
        if name == "execute_command" and self._gateway is not None:
            decision = self._check_command_consent(name, arguments, context or {})
            if not bool(decision.get("allowed")):
                return {
                    "error": "execute_command denied by consent",
                    "consent_request_id": decision.get("consent_request_id"),
                }

        invoker = getattr(self._base, "invoke", None)
        if invoker is not None:
            return _object_to_dict(invoker(name, arguments, context))
        executor = getattr(self._base, "execute", None)
        if executor is not None:
            session_id = str((context or {}).get("session_id") or "subagent")
            privacy_mode = (context or {}).get("privacy_mode") or "local_only"
            return _object_to_dict(
                executor(
                    name,
                    arguments,
                    session_id=session_id,
                    privacy_mode=privacy_mode,
                )
            )
        return {"error": "base registry has no invoke/execute method"}

    @staticmethod
    def _tool_name(tool: Any) -> str:
        """摘要：兼容 dict 与 dataclass manifest 的工具名读取。"""
        if isinstance(tool, dict):
            return str(tool.get("name") or tool.get("tool_id") or "")
        return str(getattr(tool, "name", None) or getattr(tool, "tool_id", "") or "")

    def _check_command_consent(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """摘要：兼容 check() 或 submit(ConsentRequest) 的命令执行审批。"""
        checker = getattr(self._gateway, "check", None)
        session_id = str(context.get("session_id") or "")
        if checker is not None:
            return _object_to_dict(
                checker(
                    tool_name=name,
                    arguments=arguments,
                    session_id=session_id,
                )
            )
        submit = getattr(self._gateway, "submit", None)
        if submit is None:
            return {"allowed": False}
        from offline_companion.core.plan_orchestrator import ConsentRequest

        consent_request = ConsentRequest(
            plan_id=str(context.get("plan_id") or "subagent"),
            step_id=str(context.get("step_id") or "execute_command"),
            skill_id="subagent",
            operation=name,
            purpose_type=PurposeType.TOOL_USE,
            risk_level="high",
            metadata={
                "arguments": arguments,
                "subagent_role": self._role,
                "session_id": session_id,
            },
        )
        allowed = bool(submit(consent_request))
        artifact = getattr(self._gateway, "last_artifact", None) or {}
        return {"allowed": allowed, "consent_request_id": artifact.get("request_id")}

class SubagentScheduler:
    """摘要：创建并运行受限子 Agent；Batch 4-2 构造隔离上下文与工具子集。"""

    def __init__(
        self,
        *,
        auto_router: object | None = None,
        tool_registry_factory: Callable[[SubagentContext], object] | None = None,
        consent_gateway: object | None = None,
    ) -> None:
        """摘要：初始化子 Agent 调度器。

        参数：
            auto_router: LLM 路由器，需支持 route/chat/generate 之一。
            tool_registry_factory: 受限工具注册表工厂。
            consent_gateway: 后续批次注入的 A3 审批入口。
        """
        self._router = auto_router
        self._tool_factory = tool_registry_factory
        self._gateway = consent_gateway

    def spawn(
        self,
        *,
        parent_session_id: str,
        role: SubagentRole,
        task_description: str,
        allowed_files: list[str],
        privacy_mode: str = "local_only",
        max_llm_calls: int = 10,
        plan_id: str | None = None,
        step_id: str | None = None,
    ) -> SubagentContext:
        """摘要：创建子 Agent 上下文；messages 为空，不继承父 Agent 历史。"""
        subagent_id = f"sub_{uuid4().hex[:12]}"
        return SubagentContext(
            subagent_id=subagent_id,
            parent_session_id=parent_session_id,
            role=role,
            task_description=task_description,
            allowed_files=list(allowed_files),
            system_prompt=self._build_system_prompt(role, task_description, allowed_files),
            privacy_mode=privacy_mode,
            max_llm_calls=max(1, int(max_llm_calls)),
            plan_id=plan_id,
            step_id=step_id,
        )

    def run(self, ctx: SubagentContext) -> SubagentResult:
        """摘要：执行子 Agent LLM 调用循环；有预算、有中断、可无 router 降级。"""
        if self._tool_factory is not None:
            ctx.tool_registry = self._tool_factory(ctx)
        if self._router is None:
            return SubagentResult(
                subagent_id=ctx.subagent_id,
                status="completed",
                output="[stub] subagent scheduler not yet wired to LLM",
                evidence="stub subagent completed",
            )
        ctx.messages = [
            {"role": "system", "content": ctx.system_prompt},
            {"role": "user", "content": ctx.task_description},
        ]
        tool_schemas = self._get_tool_schemas(ctx)
        while ctx.llm_call_count < ctx.max_llm_calls:
            if ctx.interrupted:
                return SubagentResult(
                    subagent_id=ctx.subagent_id,
                    status="failed",
                    output="",
                    error="interrupted",
                )
            ctx.llm_call_count += 1
            try:
                response = self._route(ctx, tool_schemas)
            except (RuntimeError, TypeError, ValueError) as exc:
                return SubagentResult(
                    subagent_id=ctx.subagent_id,
                    status="failed",
                    output="",
                    error=f"LLM route error: {exc}",
                )
            assistant_message: dict[str, Any] = {"role": "assistant", "content": response.content}
            if response.tool_calls:
                assistant_message["tool_calls"] = response.tool_calls
            ctx.messages.append(assistant_message)
            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_result = self._execute_tool_call(ctx, tool_call)
                    ctx.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(tool_call.get("id") or ""),
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )
                continue
            if ctx.role == "reviewer":
                return self._parse_reviewer_result(ctx, response)
            return SubagentResult(
                subagent_id=ctx.subagent_id,
                status="completed" if not ctx.interrupted else "failed",
                output=response.content,
                evidence=f"completed in {ctx.llm_call_count} LLM calls",
                error="interrupted" if ctx.interrupted else None,
            )
        last_content = ""
        if ctx.messages and ctx.messages[-1].get("role") == "assistant":
            last_content = str(ctx.messages[-1].get("content") or "")
        return SubagentResult(
            subagent_id=ctx.subagent_id,
            status="timeout",
            output=last_content,
            evidence=f"exhausted {ctx.max_llm_calls} LLM calls",
            error="max_llm_calls exceeded",
        )

    def _route(
        self,
        ctx: SubagentContext,
        tool_schemas: list[dict[str, Any]] | None,
    ) -> SubagentRouterResponse:
        """摘要：调用注入的 router 并归一化响应。"""
        route = getattr(self._router, "route", None)
        if route is not None:
            return _normalize_router_response(
                route(
                    messages=ctx.messages,
                    system_prompt=ctx.system_prompt,
                    privacy_mode=ctx.privacy_mode,
                    tools=tool_schemas,
                )
            )
        chat = getattr(self._router, "chat", None)
        if chat is not None:
            return _normalize_router_response(
                chat(
                    messages=ctx.messages,
                    system_prompt=ctx.system_prompt,
                    privacy_mode=ctx.privacy_mode,
                    tools=tool_schemas,
                )
            )
        generate = getattr(self._router, "generate", None)
        if generate is not None:
            return SubagentRouterResponse(
                content=str(
                    generate(
                        system_prompt=ctx.system_prompt,
                        history=ctx.messages,
                        user_message=ctx.task_description,
                    )
                ),
                tool_calls=[],
                finish_reason="stop",
            )
        raise TypeError("subagent router must provide route(), chat(), or generate()")

    def _execute_tool_call(self, ctx: SubagentContext, tool_call: dict[str, Any]) -> dict[str, Any]:
        """摘要：执行单个工具调用，返回普通字典。"""
        if ctx.tool_registry is None:
            return {"error": "no tool_registry available"}
        if ctx.interrupted:
            return {"error": "interrupted before tool execution"}
        name = str(tool_call.get("name") or "")
        arguments = tool_call.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        return ctx.tool_registry.invoke(
            name,
            arguments,
            {
                "session_id": ctx.parent_session_id,
                "privacy_mode": ctx.privacy_mode,
                "subagent_id": ctx.subagent_id,
                "subagent_role": ctx.role,
                "plan_id": ctx.plan_id or "",
                "step_id": ctx.step_id or "",
            },
        )

    def _parse_reviewer_result(
        self,
        ctx: SubagentContext,
        response: SubagentRouterResponse,
    ) -> SubagentResult:
        """摘要：解析 reviewer 结构化输出；解析失败时拒绝通过。"""
        content = response.content or ""
        approved: bool | None = None
        issues: list[str] | None = None
        suggestions: list[str] | None = None
        json_text = self._extract_json(content)
        if json_text is not None:
            try:
                parsed = json.loads(json_text)
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                approved = bool(parsed.get("approved"))
                raw_issues = parsed.get("issues") or []
                raw_suggestions = parsed.get("suggestions") or []
                issues = [str(item) for item in raw_issues] if isinstance(raw_issues, list) else None
                suggestions = [str(item) for item in raw_suggestions] if isinstance(raw_suggestions, list) else None
        if approved is None:
            approved = False
            issues = (issues or []) + [
                (
                    "reviewer output format error: expected JSON with "
                    f"approved/issues/suggestions, got: {content[:200]}"
                )
            ]
        return SubagentResult(
            subagent_id=ctx.subagent_id,
            status="completed" if not ctx.interrupted else "failed",
            output=content,
            evidence=f"review completed in {ctx.llm_call_count} LLM calls, approved={approved}",
            approved=approved,
            issues=issues,
            suggestions=suggestions,
            error="interrupted" if ctx.interrupted else None,
        )

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """摘要：从 LLM 输出中提取 JSON；支持裸 JSON 与 Markdown 代码块。"""
        text = text.strip()
        if text.startswith("{"):
            return text
        if "```json" in text:
            start = text.index("```json") + len("```json")
            try:
                end = text.index("```", start)
            except ValueError:
                return None
            return text[start:end].strip()
        if "```" in text:
            start = text.index("```") + len("```")
            try:
                end = text.index("```", start)
            except ValueError:
                return None
            return text[start:end].strip()
        return None

    def _get_tool_schemas(self, ctx: SubagentContext) -> list[dict[str, Any]] | None:
        """摘要：从受限工具注册表提取 function-calling schemas。"""
        if ctx.tool_registry is None:
            return None
        available = ctx.tool_registry.list_available()
        if not available:
            return None
        schemas: list[dict[str, Any]] = []
        for tool in available:
            name = RestrictedToolRegistry._tool_name(tool)
            if not name:
                continue
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": _tool_attr(tool, "description", ""),
                        "parameters": _tool_attr(tool, "parameters", _tool_attr(tool, "params_schema", {})),
                    },
                }
            )
        return schemas

    def _build_system_prompt(
        self,
        role: SubagentRole,
        task_description: str,
        allowed_files: list[str],
    ) -> str:
        """摘要：构造隔离提示词，并注入 allowed_files 文件内容。"""
        return (
            f"{self._role_instruction(role)}\n\n"
            f"## Task\n{task_description}\n\n"
            f"{self._inject_files(allowed_files)}\n\n"
            "## Isolation Discipline\n"
            "- Do not use parent conversation history.\n"
            "- Do not access files outside the allowed set.\n"
            "- Complete the task within your tool budget.\n"
        )

    @staticmethod
    def _role_instruction(role: SubagentRole) -> str:
        """摘要：按子 Agent 角色返回职责指令。"""
        if role == "implementer":
            return (
                "You are an implementer subagent.\n"
                "Your job: execute the coding task using only the files listed below.\n"
                "Produce working code changes. Do not refactor unrelated code."
            )
        return (
            "You are a reviewer subagent.\n"
            "Your job: review the implementation against the task specification.\n"
            "Check: correctness, edge cases, architecture boundary violations, missing tests.\n"
            "Return: approved (bool), issues (list), suggestions (list)."
        )

    @staticmethod
    def _inject_files(allowed_files: list[str]) -> str:
        """摘要：读取并注入允许文件内容；单文件和总量均截断。"""
        if not allowed_files:
            return "## Allowed Files\n(none)"
        blocks: list[str] = []
        total = 0
        for path_str in allowed_files:
            header = f"### {path_str}"
            path = Path(path_str)
            if not path.is_file():
                blocks.append(f"{header}\n[file not found]")
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                blocks.append(f"{header}\n[read error: {exc}]")
                continue
            original_len = len(content)
            if original_len > _MAX_FILE_CHARS:
                content = content[:_MAX_FILE_CHARS] + f"\n... [truncated, {original_len} chars total]"
            if total + len(content) > _MAX_TOTAL_CHARS:
                remaining = _MAX_TOTAL_CHARS - total
                if remaining <= 0:
                    blocks.append(f"{header}\n[skipped: total file content budget exceeded]")
                    continue
                content = content[:remaining] + "\n... [truncated: total budget]"
            total += len(content)
            blocks.append(f"{header}\n```\n{content}\n```")
        return "## Allowed Files\n" + "\n\n".join(blocks)

    @staticmethod
    def validate_file_access(file_path: str, allowed_files: list[str]) -> bool:
        """摘要：校验目标路径 resolve 后精确匹配 allowed_files，防止路径逃逸。"""
        if not allowed_files:
            return False
        try:
            resolved = Path(file_path).expanduser().resolve()
        except (OSError, ValueError):
            return False
        for allowed in allowed_files:
            try:
                allowed_resolved = Path(allowed).expanduser().resolve()
            except (OSError, ValueError):
                continue
            if resolved == allowed_resolved:
                return True
        return False


def _object_to_dict(value: Any) -> dict[str, Any]:
    """摘要：将工具执行结果转为普通字典。"""
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return {"result": value}


def _tool_attr(tool: Any, name: str, default: Any) -> Any:
    """摘要：兼容 dict 与对象属性读取工具 schema 字段。"""
    if isinstance(tool, dict):
        return tool.get(name, default)
    return getattr(tool, name, default)


def _normalize_router_response(value: Any) -> SubagentRouterResponse:
    """摘要：将 router 返回值归一化为 SubagentRouterResponse。"""
    if isinstance(value, SubagentRouterResponse):
        return value
    if isinstance(value, dict):
        return SubagentRouterResponse(
            content=str(value.get("content") or value.get("text") or ""),
            tool_calls=list(value.get("tool_calls") or []),
            finish_reason=str(value.get("finish_reason") or "stop"),
        )
    if hasattr(value, "__dict__"):
        data = asdict(value) if hasattr(value, "__dataclass_fields__") else vars(value)
        return SubagentRouterResponse(
            content=str(data.get("content") or data.get("text") or ""),
            tool_calls=list(data.get("tool_calls") or []),
            finish_reason=str(data.get("finish_reason") or "stop"),
        )
    return SubagentRouterResponse(content=str(value), tool_calls=[], finish_reason="stop")
