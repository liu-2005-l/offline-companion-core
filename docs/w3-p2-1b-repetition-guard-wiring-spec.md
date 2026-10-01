# W3-P2-1b 跨轮复读门接线规格 v0.2

日期：2026-10-01  
状态：锚定版

## 0. 冻结裁决

- 运行时阈值 `0.090`、比较符 `gt`；P2-1a 的 selected 历史值不改写。校准产物仅在 `intent_aware.runtime_threshold` 新增 `0.09`。
- 新增 `reply_copy.yaml:cross_turn_repetition_fallback`，同步 loader/schema、发布哈希、篡改判例与文案 lint。
- disabled 仍产 trace：`enabled=False`、`outcome=bypass`，first decision 为 `bypass/guard_disabled`。

## 1. 原始用户输入

同步与流式入口在身份提醒改写前保留 `raw_user_message`；`_finalize_generated_reply()` 新增同名可空参数，仅供 guard 内确认意图判定。现有 `user_message` 继续供 backend 与 retry。禁止上游预判布尔；raw 缺失时不豁免。

## 2. 审查口径

门挂在 `_finalize_generated_reply()`，与 L4 并列且不进入 L4 的 pattern/zone/family/policy/trace。previous reply 仅取 `history[-1]` 且角色必须为 assistant，否则 `not_adjacent_pair` bypass。隔轮重放不实现。

## 3. 共享重试槽位

L4 与 repetition 首扫同算、共享每轮唯一 retry。任一红则合并反馈重试；L4 反馈优先。复检 L4 红走 L4 fallback；L4 绿而 repetition 红走 repetition fallback；两者绿则 direct。确认豁免不消费槽位，总模型调用不超过两次。

## 4. 配置与常量

`PersonaExpressionConfig.cross_turn_repetition_guard_enabled=False`。运行阈值和比较符为模块常量。测试断言模块阈值等于 `intent_aware.runtime_threshold`，并从产物分数集合机械证明 `max_negative < runtime_threshold < min_captured_positive`，不得对标 selected。

## 5. Trace 与故障语义

`CrossTurnRepetitionTrace` 写 assistant message meta。guard 异常为 `fail-open-to-direct`：回复正常流出并记录 `bypass/guard_error`，不得称 fail-close，也不得跨轮熔断。

## 6. 验收

- 覆盖 direct、retry→direct、retry→fallback，以及豁免、disabled、missing previous、not adjacent bypass。
- 同步/流式均验证 raw 分线；改写后的 model-facing 输入不得污染意图判定。
- 覆盖 L4×guard 六格矩阵、L4 fallback 优先、模型调用上限、独立文案发布链、三字段配置、异常 fail-open 与 L4 零漂移。

## 7. 回写

因果表记录本规格锚、隔轮重放边界，以及 `intent_aware.runtime_threshold=0.09`；字段不放根级或 strict，selected 保留。
