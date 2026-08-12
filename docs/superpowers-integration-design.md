# Superpowers 强任务锚定集成设计

> **状态**：✅ 强任务锚定 + Subagent 基础设施闭合  
> **闭合日期**：2026-08-11  
> **测试基线**：`560 passed, 3 skipped`

## 目标

解决复杂任务中步骤停留在元模板、缺少具体产出和验证证据的问题。实现采用三层冗余约束：

1. **Iron Laws**：明确要求具体计划、逐步验证和用户控制。
2. **HardGate**：阶段推进必须经过 `skill_advance_stage`，前置未完成时返回 `blocked`。
3. **Verification Iron Law**：阶段完成必须附最新测试或运行证据，“写了 ≠ 跑了”。

## 阶段 1：写作标准与 Bootstrap

> **状态**：✅ 已闭合（2026-08-11，`455 passed, 3 skipped`）

- `coding-agent` 改为 Iron Laws、Reasoning、Procedure 三段式规范。
- `execution.md` 强制逐阶段执行、验证和等待用户确认。
- `verification.md` 禁止无运行证据声明完成。
- `writing-plans` 强制精确路径、完整代码、命令和预期输出。
- B1 在身份锁之后注入 `SKILL_BOOTSTRAP_PROMPT`，建立 Skill 感知层。

## 阶段 2：Skill 路由与语义触发

> **状态**：✅ 已闭合（2026-08-11，`461 passed, 3 skipped`）

- 新增 A2 `SkillDecisionEngine`，扫描可信 `skills/*/SKILL.md` frontmatter。
- 编码请求至少命中两个 description 关键词才激活 Skill，降低单关键词误触。
- 路由优先级保持 `memory > clarify > skill > chat`。
- 激活 Skill 全文作为 system prompt 注入，顺序为身份 → Bootstrap → Skill → 记忆上下文。
- 路径使用 `Path.resolve()` 与 `relative_to()` 校验，拒绝越出可信 `skills/` 根目录。

### 与初始方案的实现差异

- 未修改 B2 专用 `memory_lifecycle/semantic_extractor.py`，避免记忆识别与 A2 Skill 路由混合职责。
- 使用独立 `shell/skill_router.py`，保持 B/C 不依赖 Shell 的分层边界。
- 使用双关键词确定性匹配，不引入 embedding 或 hash-bow 依赖。

## 阶段 3：硬门禁与执行状态跟踪

> **状态**：✅ 已闭合（2026-08-11，`468 passed, 3 skipped`）

### 前置债务：PlanStore 持久化

> **状态**：✅ 已闭合（步骤 0，`454 passed, 3 skipped`）

- 生产 `PlanOrchestrator` 改用 `StateManagerPlanStore`，快照写入 SQLite。
- Auto Turn 可按 `plan_id` 在进程重建后恢复 `PlanContext`。
- 旧 `desktop_plans.json` 接口标记废弃，等待后续清理。

### 阶段 3 本体

- `coding-agent` frontmatter 声明阶段序列：`brainstorming → planning → tdd → review → finalize`。
- 新增 SQLite `skill_executions` 表，持久化阶段状态、证据与时间。
- `HardGate` 检查所有前置阶段；跳阶段和未知阶段均拒绝。
- 新增本地 builtin Tool `skill_advance_stage`，支持 `start / complete / fail`。
- `session_id` 由宿主上下文注入，LLM 参数中的伪造值会被移除。
- `complete` 强制提供 evidence，阶段未开始时不能直接完成。

### 与初始方案的实现差异

- 未知阶段不放行，改为 `unknown_stage` 阻断，避免用拼写变体绕过门禁。
- 完成和失败操作仅允许从 `executing` 状态转换，避免不存在的阶段被伪造为完成。
- Tool 通过宿主注册函数接入生产 `ToolRegistry`，不让 LLM 自报 `session_id`。

## 阶段 4：Verification 强化与 Subagent 基础设施

> **状态**：✅ 已闭合（2026-08-11，4-1→4-4；`560 passed, 3 skipped`）

- `verification.md` 增加完整测试套件、pass/fail 计数、skip 报告和 evidence 要求。
- 增加禁止项：不得用“看起来正确”“应该没问题”或“写了测试”替代实际运行结果。
- `coding-agent/SKILL.md` 更新 `code-implementer` / `code-reviewer` 调度状态。
- Subagent 基础设施实现隔离上下文、受限文件集、调度生命周期、角色工具白名单和结构化 reviewer 协议。
- `execute_command` 走 A3 consent，审计链路携带 `plan_id` / `step_id`。
- 生产接线使用本地 `backend.generate()` adapter；本地路径不支持 function calling，工具自主调用留给未来云端 adapter。

### 实现边界

- 子 Agent 不继承父 Agent messages、记忆或人格上下文。
- implementer 本地路径只能生成文本输出，不直接执行文件写入。
- reviewer 必须返回 `approved/issues/suggestions` JSON；解析失败视为 `approved=false`。
- 当前禁止子 Agent 嵌套分派；并行子 Agent 与 SpecReviewer 角色后续实现。

## 执行顺序

| 顺序 | 工作项 | 状态 |
|---:|---|---|
| 0 | PlanStore SQLite 持久化还债 | ✅ 完成 |
| 1 | Iron Laws + Bootstrap 注入 | ✅ 完成 |
| 2 | Skill 路由 + 语义触发 | ✅ 完成 |
| 3 | HardGate + 执行状态跟踪 | ✅ 完成 |
| 4 | Verification 强化 + Subagent 基础设施 | ✅ 完成 |
| 5 | 文档与实施基线同步 | ✅ 完成 |

## 七阶段能力映射

| Superpowers 能力 | Offline Companion 映射 | 当前状态 |
|---|---|---|
| Brainstorming | `coding-agent` 的 `brainstorming` 阶段 | ✅ HardGate 管控 |
| Writing Plans | `writing-plans` Skill + `planning` 阶段 | ✅ Iron Laws 已落地 |
| Test-Driven Development | `coding-agent` 的 `tdd` 阶段 | ✅ HardGate 管控 |
| Executing Plans | `PlanOrchestrator` + SQLite PlanStore | ✅ 可持久化恢复 |
| Requesting Code Review | `review` 阶段 + Verification 规则 + reviewer 协议 | ✅ 已闭合 |
| Verification Before Completion | `verification.md` + evidence 强制 | ✅ 已闭合 |
| Subagent-Driven Development | 隔离上下文与双角色调度 | ✅ 基础设施已闭合 |

## 实现文件

1. `skills/coding-agent/SKILL.md`
2. `skills/coding-agent/execution.md`
3. `skills/coding-agent/verification.md`
4. `skills/writing-plans/SKILL.md`
5. `src/offline_companion/core/persona_session/session.py`
6. `src/offline_companion/shell/skill_router.py`
7. `src/offline_companion/core/skill_execution_tracker.py`
8. `src/offline_companion/core/hard_gate.py`
9. `src/offline_companion/shell/tool_registry/skill_advance_stage.py`
10. `src/offline_companion/shell/tool_registry/registry.py`
11. `src/offline_companion/shell/tool_registry/invoker.py`
12. `src/offline_companion/core/subagent_types.py`
13. `src/offline_companion/core/subagent_scheduler.py`
14. `tests/test_subagent_scheduler.py`
15. `docs/subagent-infrastructure-design.md`

## 剩余债务

- 删除已废弃的 `desktop_plans.json` 读写接口与历史文件。
- 云端模型 adapter 支持可靠 function calling 后，再开放 implementer 自主工具调用。
- 将 `ConsentRequest` 移出 `plan_orchestrator.py`，打破 subagent consent 懒加载循环依赖。
- SpecReviewer、并行子 Agent 与子 Agent 嵌套分派保持禁用或后续设计。

## 闭合记录

2026-08-11 完成步骤 0 与阶段 1-4，共五个 Batch；测试基线从 `454 passed` 提升至 `468 passed`，未引入回归。强任务锚定的 Iron Laws、Skill 路由、阶段硬门禁、SQLite evidence 和完成验证已形成闭环。

2026-08-12 完成 Subagent 基础设施 Sprint 4-1→4-4：DTO 与 scheduler stub、隔离 prompt 和受限工具、LLM loop 与协作式中断、reviewer 审查协议、A3 consent 审计链路与本地 backend adapter。Batch 4-4 窄测 `45 passed`，全量基线 `560 passed, 3 skipped`。
