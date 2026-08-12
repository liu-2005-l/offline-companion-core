"""subagent_types：子 Agent 调度 DTO。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SubagentRole = Literal["implementer", "reviewer"]
SubagentStatus = Literal["running", "completed", "failed", "timeout"]


@dataclass
class SubagentContext:
    """摘要：子 Agent 执行上下文；不继承父 Agent 对话历史。"""

    subagent_id: str
    parent_session_id: str
    role: SubagentRole
    task_description: str
    allowed_files: list[str]
    system_prompt: str
    messages: list[dict[str, str]] = field(default_factory=list)
    privacy_mode: str = "local_only"
    max_llm_calls: int = 10
    llm_call_count: int = 0
    interrupted: bool = False
    tool_registry: object | None = None
    plan_id: str | None = None
    step_id: str | None = None


@dataclass
class SubagentResult:
    """摘要：子 Agent 完成结果；reviewer 可额外返回审查字段。"""

    subagent_id: str
    status: SubagentStatus
    output: str
    evidence: str | None = None
    approved: bool | None = None
    issues: list[str] | None = None
    suggestions: list[str] | None = None
    error: str | None = None


@dataclass
class SubagentRouterResponse:
    """摘要：子 Agent LLM 调用归一化响应。"""

    content: str
    tool_calls: list[dict[str, Any]]
    finish_reason: str
