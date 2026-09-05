# 人格约束 P3-A1.1 闭合修正规格

版本：v0.2（R3 裁决与实现落位稿）

状态：实现与机器验收完成，待 TA trace 裁决 A1 整体闭合

上游：`docs/persona-constraint-p3-a1-persistence-spec-draft.md`、A1 实现锚 `844942e`

## 0. 裁决基线

A1 五问 trace 中 Q3 原子事务通过；Q1、Q2、Q4、Q5 进入本修正批。A1.1 全绿前，A1 不得标记闭合。

## 1. R1：第二真实进程恢复

T5 保留“第一子进程在 SQLite commit 后、context publish 前被强杀”的数据恢复段，并新增第二个 `spawn`
进程。第二进程必须调用完整 `bootstrap_ui_session()`，不得由 pytest 父进程直接调用
`DesktopSessionBindingService.restore_or_create()` 代替启动链。恢复后必须同时核对 SQLite canonical、context provider、
ConversationOrchestrator、EventStream、Auto、Consent 与 sample 组件绑定。

## 2. R2：session holder 完整性防线

同步重绑的性能路径保留，但绑定对象与字段必须由单一 `BOOTSTRAP_SESSION_HOLDER_BINDINGS` 注册表驱动。测试遍历同一
注册表验证所有条目，新增注册项若没有正确重绑必须立即失败，禁止另建一份测试清单。

长期工程纪律：每轮或每次操作需要“当前桌面会话”的组件必须从 `DesktopSessionContextProvider.capture()` 捕获一次并在
该操作内固定使用；禁止新增长期缓存的裸 `session_id` 或当前 EventStream。任务、消息与 subagent 已经携带的历史
session 归属不属于“当前桌面会话”，不得在 persona 切换时改写。

## 3. R3：Consent pending 随旧会话挂起

裁定方案 a：pending consent 在创建时绑定当前 session。切换后旧 pending 保留但对新会话不可见、不可决策、不可续传；
运行时重新绑定旧 session 后恢复可见，状态不得丢失。Consent 不得迁移到新会话，也不得因 persona 切换自动批准、拒绝
或过期。Conversation pending turn 与 Tool pending action 必须执行同一 session 可见性检查。

## 4. R4：幂等键跨重启

`switch_request_id` 继续持久化于 `sessions` 并受部分唯一索引约束。新进程携带旧 key 重试时：同 target 且该 session
仍为 canonical，返回首次结果并标记 `idempotent_replay=true`；target 不同或 canonical 已前移，返回 409 且零写入。

## 5. R5：快照来源枚举

来源只允许：

- `a1_persona_system_prompt`：A1 基础人格 system prompt；
- `legacy_backfill`：无法证明创建时原件的旧会话回填；
- `p3_a2_l1_assembled`：A2 接线后冻结的 L1 最终静态组装 prompt。

旧值 `bootstrap` 与 `persona_switch` 迁移到 `a1_persona_system_prompt`；迁移同时改写 canonical JSON 并重算 SHA-256。
未知来源读写均拒绝。A2 只能把新会话来源切到 `p3_a2_l1_assembled`，不得改写旧会话快照。

## 6. 验收行

- [x] R1 第二真实进程完整 bootstrap 恢复通过；
- [x] R2 注册表驱动重绑与枚举断言通过；
- [x] R3 新会话隐藏/禁续旧 pending，重绑旧会话后状态恢复；
- [x] R4 跨重启 replay 与 canonical 前移冲突两判例通过；
- [x] R5 三值枚举、旧值迁移、哈希重算与未知值拒绝通过；
- [x] A1 相关窄测、Ruff、全量 pytest 与 `git diff --check` 通过；窄测 `133 passed`，全量
  `1306 passed, 3 skipped`，高于 `1299 passed` 基线。
