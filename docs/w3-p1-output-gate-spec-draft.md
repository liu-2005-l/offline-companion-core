# W3-P1 出口检测改造规格草案（v0.4）

日期：2026-09-25
状态：v0.4 定稿（锚定版）——2026-09-25 22:52 锚定终验阻断项已补（消费面闭环），正式锚定
定性：扩展现有 L4 单一权威并退役 dormant C 臂——零新检测机制、零动作变更、纯出口覆盖批
文档纪律：不含排期时间估算。行号来源 = TA repo trace 实锚（2026-09-25 三轮）。

## 修订记录

- v0.1（21:38）：初稿，凭记忆快照起草，含 Q1-Q8 待答；
- v0.2（22:17）：五项必修 + Q1-Q8 修订（`context_guard` 删除 / P36/P39 维持 / 分母收窄 / `remind_inject` 改独立 pending / E1 fail-close 列新增）；
- v0.3（22:33）：第四 zone 与 `remind_inject` 输出侧动作整案否决（冻结条款 `v1_5:189` / `w2-report:76` + `first_matching_zone` 三排位全死）；E3 四态 exit；E1 fail-close 载体五环节；覆盖率证明权威重构；锚点互换修正；D-1～D-4 提交过秤；
- v0.4（22:45）：按第三轮过秤机械修订：
  - E1/E2 共享入口分叉（D-1 条件落定）：`_finalize_generated_reply()` 为 E1/E2 共用，内部吞异常会绕开 E2 现有 shell catch、破坏 SSE fail-close；且 shell 零改动无法写 `status="error"`（`_append_assistant_message()` 默认 `completed`，`conversation_orchestrator.py:302`）。物理形态按 §3.4 五点重写；
  - D-2 钉结构：fail-close 文案为全局顶层键 `l4_fail_close_copy`，不进 `reply_copy.<persona>.l4_fail_close`（否则 15 条扩 20 条且基础设施故障被人格化；严格 schema `assets.py:41` + `reply_copy.yaml:8`）；五条纪律入规格（§3.5）；
  - D-4 落定：`direct` 已是现有 `PersonaL4Outcome`（`l4.py:23`），删除“新增枚举值”，E3 复用现有 `L4_DIRECT` 与 `_l4_trace(..., outcome=L4_DIRECT)`；
  - 事实修正：`_identity_question_reply()` 唯一实际调用点 `session.py:921`（`:976` 为定义；`:682/:809` 为同步/流式消费点），接线语义按“单调用点挂载 + 双消费点分派”重写（§3.2）；
  - 层级修正：`local_storage_denial` / `companion_role_denial` 是 family 非 zone，§6.3/AC-13 改为“zone + family 分列归档”；
  - 判例补强：retry 后第二次 `resolve_l4()` 扫描异常（AC-7b）；W2 runner 判例钉错误码 + 脚本可启动 + 其他 arm 可用（AC-11）。
- v0.4 定稿补丁（22:52，锚定终验阻断项）：
  - fail-close 消费面闭环：`assemble_reply()` 生产结果存在六个消费面，此前只钉了 `_execute_local_prepared()` 一个。旁路消费者会破坏“YAML 字节即正文 / `status=error` / `error_code` 传播 / 失败不冒充成功”四项。§3.4 新增消费面全景表 + 统一不变量；
  - §3.4 措辞修正：“shell 捕获：同步 `assemble_reply()` catch”改为“core 同步包装捕获”；shell 的工作是识别结构化失败结果；
  - §3.1 分母补入知识回答出口；Auto/plan 维持排除域，但增加“失败结果不冒充成功”硬条款；
  - 新增 AC-15/16/17（消费面三判例）。

## 1. 现状与范围

### 1.1 三出口现状（实锚）

| 出口 | 现状 | 实锚 |
| --- | --- | --- |
| E1 同步普通响应 | L4 已挂载（`_finalize_generated_reply()` → `resolve_l4()`，首扫 + retry 后二扫）；无 fail-close，执行异常向上抛 | `session.py:492/:575` |
| E2 validated 缓冲流 | L4 已挂载（缓冲审计后回放），异常走 shell catch → SSE error 帧，fail-close 现成 | `session.py:833`、A4 spec `:69`、A4 判例 `:406` |
| E3 确定性早退 | 完全绕过 L4：`_identity_question_reply()` 唯一调用点 `:921`，同步消费 `:682` / 流式消费 `:809` 接收产物；早退上下文已组装 | `session.py:921/:976/:682/:809` |

`PersonaSessionCore` 内唯一确定性回复生产点 = `_identity_question_reply()`。

### 1.2 C 臂现状与退役范围

- 三开关默认 `false`，生产未启用；L4 启用后旧 C 臂已被 `l4_trace.enabled` 抑制（`expression.py:46`、`session.py:723`）；
- 退役范围（AC-11 收窄版）：仅 `identity_exit_guard_enabled` 开关 + C 臂 detector/action/fallback 分支；`expression.py` 的 A/B 开关与近端注入零触碰（留 P2 单独裁决）；
- W2 runner（`scripts/run_persona_expression_w2.py`）：C arm 改稳定拒绝（错误码 + 拒绝语义），不得悬空 import；判例钉“错误码正确 + 脚本可启动 + 其他 arm 可用”三件。

### 1.3 范围外（显式）

- B 臂近端注入（P2）；
- 4-gram 重校与 P36/P39 动作/阈值变更（W3 重校批，等 P4）；
- 输入侧提醒强化（`identity_near_prompt_enabled` 现状维持，P2/独立规格）；
- W2 数据资产（只读归档）。

## 2. 设计总纲

### 2.1 检测权威

单一权威 = L4 执行器（`resolve_l4` / `scan_l4`）。零新检测器、零新 zone、零新 action。C 臂退役（§1.2）。

### 2.2 模式族增量（唯一内容变更）

W2-C 比现有 L4 多出的模式逐项并入 `identity_cliff` 的现有或新增 family，动作沿用 `retry_then_fallback`（冻结分工：输出侧全量检测继续 retry/fallback，`v1_5:189` / `w2-report:76`）。

交付物：迁移对照表（W2-C 模式 → cliff family 归属 / 与既有模式重复项排除），随 P1-1 提交。

### 2.3 guard 口径（冻结现状）

`requires_display_name_absent` 专用字段维持（`yaml:15`、`lint.py:64`、`l4.py:118` 扫描跳过语义）；并入 family 按需声明该字段（S07/S09 含名回复放行形态迁移为判例）。guard 通用化不做。

匹配口径冻结：名字权威 = 画像覆盖 → persona 配置 → 清洗 32 字符（`session.py:257`）；匹配 = 去空白后完整字符串包含、区分大小写、无昵称/部分匹配/NFKC；零 FP 优先。

## 3. 三出口接线规格

### 3.1 分母定义（冻结，含锚定终验补丁）

覆盖率分母 = 所有 `_constraints_managed()` 的本地 `PersonaSessionCore` 回复出口轮次，含确定性身份回复 + 知识检索回答出口。安全固定回复、记忆确认、Consent、云端路径、plan/card 路由不属于人格 L4 分母。

Auto/plan 维持排除域（B0 契约同款纪律），但附硬条款：排除域内的失败结果不得冒充成功——Auto 两个调用点（`auto_turn_orchestrator.py:126/:146`）收到 `fail_closed` 时必须映射为既有 Auto error/failed 终态，不得包装为成功 result。

### 3.2 E3：四态结构化 exit

`_identity_question_reply()` 唯一调用点（`:921`）挂 L4 扫描，产出结构化 exit；消费点（`:682` 同步 / `:809` 流式）按 kind 分派：

| kind | 语义 | 动作 | trace |
| --- | --- | --- | --- |
| `absent` | 非身份问题 | 正常生成路径 | 无 L4 trace 需求 |
| `direct` | 安全直出 | 产出文案 | `enabled=True, outcome=L4_DIRECT`（复用现有枚举 `l4.py:23`，`_l4_trace(..., outcome=L4_DIRECT)`） |
| `fallthrough_hit` | L4 命中 | 丢弃 `identity_reply`，退全链；后续动作由 E1 分发 | 最终以 E1 trace 为准 |
| `fallthrough_error` | 检测异常 | 同上退全链 | 同上 |

形态：结构化内部结果或单一 exit helper（`str | None` 不够——`None` 混淆三态）。E3 自身不设 zone 差异化动作，E1 是唯一动作分发点。

### 3.3 E3 失败双分支

- 一次性异常：退全链可恢复（上下文已组装，忽略 `identity_reply` 继续 `backend.generate()`）；
- 持续异常：必须落到 E1 fail-close（§3.4），不承诺必得正常模型回复。

### 3.4 E1 fail-close（新增交付，物理形态钉死）

异常传播链（E1/E2 分叉）：

1. core：`_finalize_generated_reply()` 对首次与 retry 后两次 `resolve_l4()` 的执行异常均抛稳定类型异常（`PersonaL4ExecutionError`），不吞；
2. 同步：`assemble_reply()` 捕获，返回带 `fail_closed` / `error_code` 的结构化结果；
3. 流式：`assemble_reply_stream()` 不吞异常，继续进入 E2 现有 shell catch（SSE error 帧 fail-close 零漂移）；
4. 落库：`_execute_local_prepared()` 识别 `fail_closed`，跳过 `reformat_local_reply()`，逐字节写固定文案 + `status="error"` + meta 标记（`l4_fail_closed`）；
5. `TurnResult` / HTTP payload 携带稳定错误码 `error_code: "persona_l4_fail_closed"`，`run_turn` 的 `turn_end` 同步记 `error`；客户端从 `200 + error_code` 识别降级。

| 环节 | 载体 |
| --- | --- |
| core 报告 | 稳定类型异常（两种扫描时机均抛） |
| core 同步包装捕获 | `assemble_reply()` catch（core 侧），产出结构化 `fail_closed` 结果；流式不 catch |
| HTTP 形态 | `200 + payload.error_code`（非 500；D-1 落定） |
| 固定文案 | `reply_copy.yaml` 全局顶层键 `l4_fail_close_copy`（§3.5） |
| 消息行状态 | `status="error" + meta.l4_fail_closed` |

消费面全景与统一不变量：`assemble_reply()` 的 `fail_closed` 结果有六个消费者，任何消费者不得把 fail-close 结果当正常模型输出：

| 消费面 | 位置 | 处置 |
| --- | --- | --- |
| 普通同步 | `conversation_orchestrator.py:548` | 原始 `l4_fail_close_copy` 逐字节 + `status="error"` + 稳定机器码 |
| 云失败后本地 fallback | `conversation_orchestrator.py:941` | 同上；必须在 `_local_fallback_reply()` 的 reformat 与 `LOCAL_FALLBACK_PREFIX`（`:956/:962`）之前分支，fail-close 结果不走 fallback 美化路径 |
| Auto 步骤输出 | `auto_turn_orchestrator.py:126` | 映射既有 Auto error/failed 终态，不产生成功 result |
| Auto 最终总结 | `auto_turn_orchestrator.py:146` | 同上 |
| 知识检索回答 | `knowledge_turn.py:91` | 原始逐字节 + `status="error"` + 稳定机器码；在 reformat 与按 completed 落库（`:88`）之前分支，不作正常知识回答 |
| `_execute_local_prepared` | session 内（v0.4 已钉） | 跳过 `reformat_local_reply()`，逐字节写 + `status="error"` + meta 标记 |

统一不变量：任何 `AssembleReplyResult.fail_closed=True` 的消费者，必须在 reformat、prefix、语义抽取和正常持久化之前分支进入失败处置。

### 3.5 fail-close 文案纪律（D-2 落定）

`l4_fail_close_copy` 为 `reply_copy.yaml` 全局顶层键，不进 `reply_copy.<persona>.l4_fail_close`——基础设施故障不人格化，15 条不扩 20 条；严格 schema 见 `assets.py:41` + `reply_copy.yaml:8`。

五条纪律：

1. loader 强校验并进入组装产物（`source_payloads` 链，对齐 A5 `fallback_copy` 先例）；
2. 通过五项静态 lint；
3. 字符级篡改拒绝（corpus SHA → manifest SHA 发布链）；
4. fail-close 时该文案不再经过 L4 扫描（防故障递归）；
5. 不经 reformatter——YAML 字节即最终正文。

## 4. 动作边界

| 对象 | 动作 | 变更 |
| --- | --- | --- |
| `identity_cliff` 全部 family（含并入的 W2-C 模式） | `retry_then_fallback` | 零变更 |
| `local_storage_denial` / `companion_role_denial`（family，`yaml:25/:18`） | `retry_then_fallback` | 零变更（锚点：`local_storage=:25`，`companion=:18`） |
| 输出侧 `remind_inject` | 不存在 | 冻结裁决（`v1_5:189` / `w2-report:76`）：输入侧身份意图负责提醒注入，输出侧继续 retry/fallback；输出侧提醒立项 = 显式变更冻结裁决 + 迁移 + hard→soft 安全基线重跑 |
| 输入侧 `identity_near_prompt_enabled` | 现状维持 | 零触达，强化留 P2/独立规格 |

## 5. 失败态口径

- patterns 加载：启动期 fail-close，运行时无重载（既有）；本规格失败态只写扫描器/执行器异常，不写“patterns 加载运行时异常”；
- E1：新增 fail-close（§3.4）；
- E2：现成 fail-close 零漂移（AC-8）；
- E3：双分支（§3.3）；
- 共同验收语义：任何失败态下未审计内容零泄漏。

## 6. 统计口径与覆盖率证明

### 6.1 覆盖率

分母（§3.1 冻结）内轮次，权威证明：

1. 同步结果：轮次 trace 在场断言；
2. 流式 done：L4 trace 在场断言；
3. 三出口结构判例：“到达检测点”探针/调用断言。

目标 = 100%。

### 6.2 EventStream 降位

可失败镜像：只做运行归档并记录镜像失败（判例），不作为 100% 覆盖权威。

### 6.3 重校材料归档

zone + family 分列命中归档（W3 重校批输入）：cliff/local_storage/companion family 命中数、guard 拦截数（S07/S09 形态）、E3 fallthrough 计数。动作裁决零参与。

## 7. 验收行（AC 全表）

| # | 验收行 |
| --- | --- |
| AC-1 | E1/E2 出口判例：检测点在场探针断言（同步/流式各一） |
| AC-2 | E3 四态：`absent` 与 `direct` 判例，同步+流式双路径；`direct` 断言 `enabled=True + outcome=L4_DIRECT`（复用现有枚举） |
| AC-3 | `fallthrough_hit` → 退全链，断言 E1 检测点被调用（绿在正确机制上，禁绿在“输出正常”） |
| AC-4 | `fallthrough_error` 一次性 → 退全链 → E1 成功 → 正常回复 + E1 trace 在场 |
| AC-5 | `fallthrough_error` 持续 → 落 E1 fail-close 固定文案；失败候选零泄漏断言 |
| AC-6 | W2-C 模式并入：迁移对照表逐项 + 正控/负控 + S07/S09 含名放行（guard 判例） |
| AC-7a | 首次 `resolve_l4()` 异常 → fail-close 全链（同步） |
| AC-7b | retry 后第二次扫描异常 → fail-close 全链（同步） |
| AC-7c | 流式 E2 异常穿透：`assemble_reply_stream` 不吞 → shell catch → SSE error 帧（E2 现有语义零漂移） |
| AC-7d | fail-close 文案纪律：不经 L4 扫描（防递归负控）+ 不经 reformatter（字节等值断言）+ `status="error"` + meta 标记 + `error_code` 在场 |
| AC-8 | E2 现有 fail-close 零漂移回归判例 |
| AC-9 | 既有 zone/family 动作零漂移（cliff 全 family + local_storage + companion 均 `retry_then_fallback`）+ 输入侧 `identity_near_prompt_enabled` 零触达 |
| AC-10 | YAML 变更发布链：corpus SHA → manifest SHA（`assets.py:18/:194`）+ 字符级篡改拒绝判例 |
| AC-11 | 退役：`identity_exit_guard_enabled` + C 臂 detector/action/fallback 删除后全量回归；A/B 开关在场且零引用变更；W2 runner 错误码正确 + 脚本可启动 + 其他 arm 可用 |
| AC-12 | 覆盖率三权威判例 + EventStream 镜像失败记录判例 |
| AC-13 | zone + family 分列命中归档（§6.3 四类计数） |
| AC-14 | 全量回归零新告警 + 三出口检测延迟增量数字 |
| AC-15 | 云失败 → 本地 fallback → L4 异常：无 prefix、无 reformat、error 行、HTTP 200 + `error_code` |
| AC-16 | knowledge 路径 L4 异常：固定文案逐字节、error 行、不作正常知识回答 |
| AC-17 | Auto 两调用点（`:126/:146`）L4 异常：进入 error/failed 终态，不产生成功 result |
| X-1 | 显式不做：输出侧 `remind_inject`（冻结裁决锁）/ guard 通用化 / family 级 action / M=10 或持久化 cooldown / 输入侧提醒强化 |
| X-2 | 行号漂移容错：实现期发现行号漂移时语义定位优先，漂移记档不改验收行 |

## 8. 发布链机械步骤

修改 `l4_patterns.yaml` 或 `reply_copy.yaml` → `persona_constraint_corpus.yaml` 源 SHA 重算 → `assets.py:18` manifest SHA 重算 → 篡改拒绝判例重跑 → 发布链入口 `assets.py:194`。

## 9. 过秤裁决落定表

| # | 裁决 | 状态 |
| --- | --- | --- |
| D-1 | HTTP 200 + 确定性失败回复 + `message.status="error"` + 稳定机器码 `persona_l4_fail_closed`；E1/E2 共享入口分叉（同步 catch / 流式不吞） | 落定（§3.4） |
| D-2 | 全局顶层键 `l4_fail_close_copy` + 五条纪律 | 落定（§3.5） |
| D-3 | W2 runner C arm 稳定拒绝 + 三件判例 | 落定（§1.2/AC-11） |
| D-4 | `direct` 复用现有 `PersonaL4Outcome`（`l4.py:23`），零枚举变更 | 落定（§3.2） |

## 10. 实锚记录

三轮过秤累计实锚：

- `session.py:492/:575`（E1 双扫描）/ `:833`（E2）/ `:921`（E3 唯一调用点）/ `:976`（定义）/ `:682/:809`（同步/流式消费点）/ `:723`（L4 抑制 C 臂）/ `:257`（名字口径）；
- `expression.py:46`（三开关默认 `false`）；
- `conversation_orchestrator.py:302`（status 默认 completed）/ `:360`（`persona_audit_pending` 只认算术 warning）/ `:548`（普通同步消费面）/ `:941`（本地 fallback 消费面）/ `:956/:962`（`_local_fallback_reply` reformat + `LOCAL_FALLBACK_PREFIX`）；
- `auto_turn_orchestrator.py:126/:146`（Auto 两调用点）；
- `knowledge_turn.py:88/:91`（知识回答 reformat + completed 落库 / 消费面）；
- `l4.py:23`（`L4_DIRECT`）/ `:73`（加载器硬校验）/ `:118`（guard 扫描跳过）；
- `lint.py:41/:64`；
- YAML `:6`（`first_matching_zone`）/ `:10/:13`（`generic_ai_self_reference` + cliff 动作）/ `:15`（guard 字段）/ `:18`（`companion_role_denial`）/ `:25`（`local_storage_denial`）；
- `assets.py:18/:41/:194`；
- `registry.py:8`；
- A4 spec `:69` + A4 判例 `:406`；
- `v1_5:189` + `w2-report:76`（冻结分工条款）。

## 11. P1-1 实现期勘误与闭合

### 11.1 消费面计数勘误

锚定版 §3.4 把“普通同步”和 `_execute_local_prepared` 分列为两个消费面；实现期 trace 证明二者是同一个物理消费者。消费面数量由 6 更正为 5，属于规格实锚计数错误，不构成实现偏离。五个物理调用点均在格式化、前缀、语义抽取和正常持久化之前紧邻处理 `fail_closed`：

| 消费面 | 漂移后调用点 | `fail_closed` 分支 | 终态 |
| --- | --- | --- | --- |
| 普通同步 / `_execute_local_prepared` | `conversation_orchestrator.py:551` | `conversation_orchestrator.py:566` | 原文 error 行 + 稳定机器码 |
| 云失败后本地 fallback | `conversation_orchestrator.py:979` | `conversation_orchestrator.py:994` | 无 reformat、无 `LOCAL_FALLBACK_PREFIX` |
| Auto 步骤输出 | `auto_turn_orchestrator.py:126` | `auto_turn_orchestrator.py:137` | `step_failed` / `plan_failed`，无成功 result |
| Auto 最终总结 | `auto_turn_orchestrator.py:152` | `auto_turn_orchestrator.py:162` | 映射既有 Auto 失败终态 |
| 知识检索回答 | `knowledge_turn.py:92` | `knowledge_turn.py:101` | 原文 error 行，不作正常知识回答 |

### 11.2 AC-2 客户端边界

AC-2 以 core `done.l4_trace` 与消息库 `meta.persona_l4_trace` 为可观测权威；不要求 HTTP SSE 对客户端暴露 trace。E3 direct 的 core 帧固定为 `recall → token → done`，其中单个 token 承载完整确定性直出文本，`done` 携带 `enabled=True + outcome=L4_DIRECT`，backend 零调用。HTTP 字节级 trace expose 不属 P1-1，进入 v1.9.x 候选池，与断开续传和 Auto 流式化并列。

### 11.3 AC-13 终裁

AC-13 验收行白纸黑字要求“zone + family 分列命中归档（§6.3 四类计数）”。P1-1 主实现提交时，逐轮 trace 已保存 zone、family 与 E3 fallthrough warning，但尚无 cliff/local_storage/companion family、guard 拦截与 E3 fallthrough 的聚合计数产物，因此诚实登记缺口 `P1-1.1`。补批新增 `scripts/summarize_w3_p1_l4_traces.py`、冻结输入/expected 与全字段等值判例，机械产出上述计数；不改变现有检测、动作或消费路径。AC-13 至此闭合。

### 11.4 AC 到判例映射

| 验收项 | 判例或物理证据 | P1-1 终态 |
| --- | --- | --- |
| AC-1 | `test_l4_sync_direct_and_observe_do_not_retry`；`test_l4_stream_buffers_bad_tokens_until_final_candidate_is_safe` | 已闭合 |
| AC-2 | `test_l4_protected_identity_reply_is_byte_preserved_without_generation`；`test_l4_protected_identity_stream_keeps_recall_token_done_shape` | 已闭合；HTTP trace 入候选池 |
| AC-3 | `test_l4_identity_hit_falls_through_to_e1_and_records_trace` | 已闭合 |
| AC-4 | `test_l4_identity_one_shot_error_falls_through_and_recovers` | 已闭合 |
| AC-5 | `test_l4_identity_persistent_error_falls_through_to_fail_close` | 已闭合 |
| AC-6 | `test_identity_cliff_detector_fixture_matrix`；`test_l4_fixture_has_fifty_paired_pattern_neighbors`；`docs/w3-p1-w2-c-pattern-migration.md` | 已闭合，50/50 TP、0/50 FP |
| AC-7a | `test_l4_sync_first_scan_failure_returns_structured_fail_close` | 已闭合 |
| AC-7b | `test_l4_sync_retry_scan_failure_returns_structured_fail_close` | 已闭合 |
| AC-7c | `test_l4_runtime_failure_is_fail_closed_and_returns_visible_error` | 已闭合 |
| AC-7d | AC-7a 调用次数负控；`test_l4_sync_fail_close_bypasses_reformat_and_persists_error_row` | 已闭合 |
| AC-8 | buffered replay、HTTP rejected bytes、backend failure、L4 runtime failure 四条既有流式判例 | 已闭合 |
| AC-9 | `test_l4_pure_policy_routes_three_zones_and_display_name_exception`；既有 retry/fallback 判例；B 臂注入判例 | 已闭合 |
| AC-10 | patterns、fallback copy、fail-close copy 三条篡改拒绝判例；冻结 SHA 判例 | 已闭合 |
| AC-11 | `test_w2_runner_rejects_retired_c_arm_but_keeps_a_and_b`；`test_arm_c_runtime_surface_is_retired_while_arms_a_and_b_remain` | 已闭合 |
| AC-12 | 同步结果 trace、流式 done trace、三出口调用探针；`test_arithmetic_retry_reassembles_correction_prompt_even_when_event_mirror_fails` | 已闭合 |
| AC-13 | `test_w3_p1_l4_trace_archive_produces_frozen_recalibration_counts`；冻结聚合 fixture；审计脚本 | `P1-1.1` 已闭合 |
| AC-14 | 全量 `1519 passed, 3 skipped`；Ruff 0；clean scan 增量 `1.126µs/scan` | 已闭合 |
| AC-15 | `test_cloud_fallback_fail_close_has_no_prefix_or_reformat` | 已闭合 |
| AC-16 | `test_knowledge_answer_fail_close_is_error_row_without_reformat` | 已闭合 |
| AC-17 | `test_conversation_plan_invoker_maps_fail_close_to_auto_failure`，含完整 `step_failed → plan_failed` 传播 | 已闭合 |
| X-1 | 源码零 `remind_inject` / C 臂 fallback / family action 新机制 | 已守住 |
| X-2 | §11.1 五对漂移后实锚 | 已回填 |

P1-1 测试净增 11：新增 15 个测试函数，其中 1 个为冻结 SHA 判例改名、3 个旧 C 臂行为判例由 1 个退役哨兵替换，最终从 1508 增至 1519。P1-1.1 另增 1 条聚合判例，闭合后总基线为 1520。
