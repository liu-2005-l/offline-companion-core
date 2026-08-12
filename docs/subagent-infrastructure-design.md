# Subagent 基础设施设计

> **状态**：✅ 4-1→4-4 已闭合  
> **日期**：2026-08-12  
> **验证**：Batch 4-4 窄测 `45 passed`；全量 `560 passed, 3 skipped`

## 目标

为强任务锚定补齐受限子 Agent 基础设施，使计划步骤可以在隔离上下文中分派给 `implementer` 或 `reviewer`，并保持本地优先、可审计、可中断。

## 已实现能力

| 批次 | 内容 | 状态 |
|---|---|---|
| 4-1 | DTO、`SubagentScheduler` stub、`PlanStep.subagent_type`、生产注入点 | ✅ |
| 4-2 | 隔离 system prompt、allowed files 注入、`RestrictedToolRegistry`、文件白名单 | ✅ |
| 4-3 | LLM loop、`max_llm_calls` 预算、协作式中断、角色工具白名单、命令 consent、privacy fallback | ✅ |
| 4-4 | `_object_to_dict` 一致性、`plan_id/step_id` 审计透传、reviewer JSON 协议、本地 backend adapter | ✅ |

## 运行边界

- 子 Agent 使用独立 `messages`，不继承父 Agent 对话历史、记忆或人格。
- `allowed_files` 采用 resolve 后精确文件匹配，拒绝 path traversal。
- `implementer` 工具白名单：`file_read` / `file_write` / `execute_command`。
- `reviewer` 工具白名单：`file_read`。
- `execute_command` 必须经过 A3 consent，审批请求携带 `plan_id` / `step_id` / `subagent_role` / `session_id`。
- 中断是协作式：LLM 调用前和工具执行前检查 `interrupted`。

## Reviewer 协议

`reviewer` 必须返回 JSON：

```json
{"approved": false, "issues": ["具体问题"], "suggestions": ["具体建议"]}
```

- `approved=false` 表示不能标记阶段完成。
- `issues[]` 放阻断项。
- `suggestions[]` 放非阻断建议。
- JSON 解析失败时，系统强制 `approved=false` 并记录格式错误。

## 生产接线

生产路径通过 A 层 `_SubagentRouterAdapter` 接本地 `backend.generate()`：

- 输入：隔离 `system_prompt`、子 Agent 消息链、可用工具名说明。
- 输出：`SubagentRouterResponse(content=..., tool_calls=[], finish_reason="stop")`。
- 当前本地后端不支持可靠 function calling，因此不会在生产本地路径自主触发工具调用。

## 已知债务

- 云端模型 adapter：接入 OpenAI 兼容 tool calls 后，再开放 implementer 自主工具调用。
- `ConsentRequest` 类型仍在 `plan_orchestrator.py`，`subagent_scheduler.py` 通过函数级懒加载避免运行时循环；后续应移入共享 consent DTO。
- SpecReviewer 角色、并行子 Agent、子 Agent 嵌套分派均未启用。

## 验证

- `tests/test_subagent_scheduler.py` 覆盖 spawn 隔离、快照兼容、工具白名单、文件白名单、LLM loop、预算耗尽、中断、consent、reviewer 协议和本地 adapter。
- Batch 4-4 聚焦验证：`.venv\Scripts\python.exe -m pytest -q tests/test_subagent_scheduler.py` → `45 passed`。
- 全量验证：`.venv\Scripts\python.exe -m pytest -q` → `560 passed, 3 skipped`。
