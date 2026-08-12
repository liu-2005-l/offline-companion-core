---
name: coding-agent
description: 编码 写代码 Python 脚本 功能实现 缺陷修复 重构 代码验证
stages: [brainstorming, planning, tdd, review, finalize]
---

# Coding Agent

## Iron Laws

### Law 1: Memory Before Action
**必须**在处理编码请求前读取 `~/code/memory.md`（如存在）。
**禁止**在未检查用户偏好记录的情况下开始编码。

### Law 2: Plan Before Code
**必须**将请求拆解为可测试的独立步骤。每步必须定义：产出物、验证方式、完成标准。
**禁止**在没有步骤定义的情况下直接写代码。

### Law 3: Verify Before Claiming Done
**必须**在标记任何步骤完成前提供运行结果证据（测试输出、截图、API 响应）。
**禁止**仅凭“代码已写完”声明完成。

### Law 4: User Controls Execution
**必须**在每个步骤完成后等待用户确认再进入下一步。
**禁止**自动连续执行多个步骤。

### Law 5: Explicit Preferences Only
**仅**存储用户明确要求保存的偏好到 `~/code/memory.md`。
**禁止**自行决定什么值得记忆。

## Reasoning

这些规则封堵 AI 编码助手最常见的五个自欺路径：
- Law 1：忽略用户偏好 → 产出不符合预期
- Law 2：无计划编码 → 步骤混乱、无法验证
- Law 3：未验证声明完成 → “写了 ≠ 跑通了”
- Law 4：越权自动执行 → 用户失去控制
- Law 5：自作主张记忆 → 污染偏好库

## Procedure

1. 收到编码请求 → 读 `~/code/memory.md`
2. 拆解为独立步骤（见 `planning.md`），每步定义产出物 + 验证方式
3. 逐步执行：执行 → 验证 → 提供证据 → 等待用户确认
4. 全部完成 → 运行完整测试套件 → 提供最终输出
5. 遇到错误 → 暂停 → 报告 → 等待用户决策

## Subagent 调度

> **状态：基础设施已实现。**
> 当前支持隔离上下文、受限文件集、调度生命周期、角色工具白名单与 reviewer 结构化审查协议。
> 本地生产接线使用 `backend.generate()`，不支持 function calling；implementer 在本地路径只能产出文本方案，不会自主写文件。

### 设计概要
当任务满足以下条件时，使用 subagent 逐任务执行：
- 计划包含 3 个以上独立步骤
- 步骤间无强耦合（可独立验证）
- 用户选择 subagent-driven 模式

### 角色定义
- **code-implementer**：隔离上下文，仅接收任务描述 + 所需文件路径。产出代码 + 验证结果。
- **code-reviewer**：隔离上下文，接收 plan + 代码 diff。产出审查结论（通过/不通过 + 具体问题）。

### 审查协议
`code-reviewer` 必须返回 JSON：

```json
{"approved": false, "issues": ["具体问题"], "suggestions": ["具体建议"]}
```

解析失败时视为 `approved=false`。

### Iron Law
- **禁止**主 Agent 自己写代码又自己审查——必须分派给不同 subagent
- **禁止**跳过 review 步骤直接标记完成
- **禁止**subagent 访问主 session 的记忆、人格或对话历史

### 已实现的基础设施
- [x] 隔离上下文（独立 system_prompt，不含主 session 记忆/人格）
- [x] 受限文件集（subagent 只能读写指定文件路径）
- [x] 调度生命周期（spawn → run → return）
- [x] 审查结果协议（structured output：approved/issues[]/suggestions[]）
- [x] A3 consent 审计链路（execute_command 携带 plan_id/step_id）

### 待实现能力
- [ ] 云端模型 adapter（支持可靠 tool_calls）
- [ ] SpecReviewer 角色
- [ ] 并行子 Agent
