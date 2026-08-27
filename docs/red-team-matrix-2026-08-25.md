# Batch E-1 红队侦察矩阵（2026-08-27）

## 口径说明

- 本轮只做侦察，不做修复；产物用于 E-2 对拍“修复前 → 修复后”。
- 预注册口径来自 `docs/red-team-batch-e-design.md`：第 2 节 14 条 + 第 4 节补录 `E8-1`，合计 15 条。
- 本轮 harness 覆盖 `PlanDecomposer`、确定性 Tool 执行、算术审计与 Tool 事件层；`NotDecomposableResult` 后续普通 chat 未调用，因此降级内容以 `fallback_notice` 与拆解决策为准。
- manifest 注册信息为一次性侦察脚本手抄复刻 `bootstrap.py` 字段；E-2 后若焙成回归常量，必须改为 import/复用生产注册表同源，避免 D-1 类漂移复发。
- 日志级别按 E-0 P-2 开 `debug`，LLM 原始输出可追；本轮所有主判例均未进入 LLM 拆解，因此无 LLM 原始输出正文。
- 临时原始 JSON 已移出仓库树：`%TEMP%\oc_e1_preregistered_2026-08-27.json`；本文档为本轮矩阵事实源。

## 汇总

| 条数 | correct | degraded-explicit | silent-fail |
|---:|---:|---:|---:|
| 15 | 6 | 3 | 6 |

## 主判例矩阵

| ID | 七族 | 输入原文 | 当前三态 | 预期终态（§7.1/§7.4） | 定位层 | 日志 / 事件依据 | 结论 |
|---|---|---|---|---|---|---|---|
| E1-1 | 负数 | `用booth算法计算负三乘七` | silent-fail | correct | 解析层 | skills `algorithm_booth>chat`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('booth算法',)；INFO:offline_companion.core.plan_decomposer:拆解路径探测: source=builtin_tool route=algorithm constraints=('booth算法',) steps=2；事件 tool/call, tool/result | 解析层中文负号丢失/结果不符: skills=['algorithm_booth', 'chat'] trace={'algorithm': 'booth', 'multiplicand': 3, 'multiplier': 7, 'bit_width': 4, 'recoding': '7 = +8 -1', 'partial_products': [24, -3], 'rounds': [{'round': 1, 'pair': '10', 'operation': 'A = A - M (0 - 3)', 'accumulator_before': 0, 'accumulator_after_operation': -3, 'accumulator_after_shift': -2, 'multiplier_after_shift': -5, 'previous_multiplier_bit': 1}, {'round': 2, 'pair': '11', 'operation': '保持 A', 'accumulator_before': -2, 'accumulator_after_operation': -2, 'accumulator_after_shift': -1, 'multiplier_after_shift': 5, 'previous_multiplier_bit': 1}, {'round': 3, 'pair': '11', 'operation': '保持 A', 'accumulator_before': -1, 'accumulator_after_operation': -1, 'accumulator_after_shift': -1, 'multiplier_after_shift': -6, 'previous_multiplier_bit': 1}, {'round': 4, 'pair': '01', 'operation': 'A = A + M (-1 + 3)', 'accumulator_before': -1, 'accumulator_after_operation': 2, 'accumulator_after_shift': 1, 'multiplier_after_shift': 5, 'previous_multiplier_bit': 0}], 'result': 21} |
| E1-2 | 负数 | `求-48和18的最大公约数` | correct | correct | 路由/执行层 | skills `algorithm_gcd>chat`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=()；INFO:offline_companion.core.plan_decomposer:拆解路径探测: source=builtin_tool route=algorithm constraints=() steps=2；事件 tool/call, tool/result | gcd 负数 abs 端到端结果 6 |
| E2-1 | 大数 | `按照booth算法计算77乘88` | correct | correct | 执行层 | skills `algorithm_booth>chat`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('booth算法',)；INFO:offline_companion.core.plan_decomposer:拆解路径探测: source=builtin_tool route=algorithm constraints=('booth算法',) steps=2；事件 tool/call, tool/result | booth 大数结果 6776 |
| E2-2 | 大数 | `求123456789和987654321的最大公约数` | correct | correct | 路由/参数转写层 | skills `algorithm_gcd>chat`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=()；INFO:offline_companion.core.plan_decomposer:拆解路径探测: source=builtin_tool route=algorithm constraints=() steps=2；事件 tool/call, tool/result | gcd 大数参数与结果正确 |
| E3-1 | 多轮指代 | `两轮：①按booth算法算3乘7 ②再用刚才的算法算5乘8` | degraded-explicit | degraded-explicit（顺手做生效则 correct） | 会话历史/降级层 | skills `-`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('booth算法',)；INFO:offline_companion.core.plan_decomposer:拆解路径探测: source=builtin_tool route=algorithm constraints=('booth算法',) steps=2；事件 第1轮 tool/call, tool/result；第2轮 无事件；fallback_notice：无法按指定方法分步执行，已转为直接回答；本地模型可能无法严格复现该方法。 | 第二轮未解析指代但显式降级 |
| E4-1 | 参数缺失 | `用booth算法算一下` | silent-fail | degraded-explicit | 路由/降级层 | skills `-`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('booth算法',)；INFO:offline_companion.core.plan_decomposer:拆解决策: action=fallback source=rule reason=no_rule_match constraints=('booth算法',)；事件 无事件 | 缺参降级不明示: reason=no_rule_match notice=None |
| E4-2 | 参数缺失 | `帮我排个序` | degraded-explicit | degraded-explicit | 普通意图降级层 | skills `-`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=()；INFO:offline_companion.core.plan_decomposer:拆解决策: action=fallback source=rule reason=no_rule_match constraints=()；事件 无事件 | 无专名缺参未编造；普通 chat/clarify 后续呈现待 UI 验证 |
| E5-1 | 降级链内容 | `按照MD5算法计算"abc"的哈希` | degraded-explicit | degraded-explicit | 降级内容层 | skills `-`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('md5算法',)；INFO:offline_companion.core.plan_decomposer:拆解决策: action=fallback source=builtin_tool reason=algorithm_tool_unavailable constraints=('md5算法',)；事件 无事件；fallback_notice：无法按指定方法分步执行，已转为直接回答；本地模型可能无法严格复现该方法。 | 可见降级；侦察器未进入 chat 正文，未发现编造内容 |
| E5-2 | 降级链内容 | `按UTF-8编码计算"你好"的字节` | silent-fail | degraded-explicit | 约束识别/降级层 | skills `-`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=()；INFO:offline_companion.core.plan_decomposer:拆解决策: action=fallback source=rule reason=no_rule_match constraints=()；事件 无事件 | 降级链不可见或生成计划: None notice=None |
| E6-1 | 措辞变异 | `3乘7的结果是14` | correct | correct | 审计提取层 | skills `-`；INFO:offline_companion.core.arithmetic_verifier:算术断言审计完成: extracted=1 failures=1 retry_allowed=False skipped=none；事件 无事件 | 算术审计识别错误断言 |
| E6-2 | 措辞变异 | `3乘7的积为14` | silent-fail | correct | 审计提取层 | skills `-`；INFO:offline_companion.core.arithmetic_verifier:算术断言审计完成: extracted=0 failures=0 retry_allowed=False skipped=missing_equality；事件 无事件 | 算术错误断言未被识别 |
| E7-1 | 工具执行边界 | `按快速排序排[]` | silent-fail | correct | 解析/降级层 | skills `-`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('快速排序',)；INFO:offline_companion.core.plan_decomposer:拆解决策: action=fallback source=rule reason=no_rule_match constraints=('快速排序',)；事件 无事件 | 空数组未正确处理: None None notice=None |
| E7-2 | 工具执行边界 | `按快速排序排[5]` | correct | correct | 执行层 | skills `algorithm_quicksort>chat`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('快速排序',)；INFO:offline_companion.core.plan_decomposer:拆解路径探测: source=builtin_tool route=algorithm constraints=('快速排序',) steps=2；事件 tool/call, tool/result | 单元素 quicksort 返回 [5] |
| E7-3 | 工具执行边界 | `按快速排序排[3,3,3]` | correct | correct | 执行层 | skills `algorithm_quicksort>chat`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('快速排序',)；INFO:offline_companion.core.plan_decomposer:拆解路径探测: source=builtin_tool route=algorithm constraints=('快速排序',) steps=2；事件 tool/call, tool/result | 全等元素 quicksort 返回 [3,3,3] |
| E8-1 | 双工具链 | `先按booth算法算3乘7再乘2` | silent-fail | degraded-explicit | 拆解/路由层 | skills `algorithm_booth>chat`；INFO:offline_companion.core.plan_decomposer:拆解路径探测: gate=R3 action=continue method_constraints=('booth算法',)；INFO:offline_companion.core.plan_decomposer:拆解路径探测: source=builtin_tool route=algorithm constraints=('booth算法',) steps=2；事件 tool/call, tool/result | 只执行第一段 booth 3×7=21，静默丢失再乘2 |

## Silent 清单与 E-2 优先级

| 优先级 | 判例 | 定位层 | 根因 | E-2 修复方向 |
|---:|---|---|---|---|
| P1 | E1-1 | 解析层 | 中文负号 `负三` 被解析为 `3`，工具正确执行了错误参数。 | 扩展中文负数解析，Booth 参数解析前保留符号。 |
| P1 | E8-1 | 拆解/路由层 | 复合指令只发射第一段 `booth 3×7`，静默丢失 `再乘2`。 | E-2 先明示降级“复合算法指令请拆分执行”；完整双工具链记 v6 候选。 |
| P1 | E4-1 | 路由/降级层 | 有方法约束但参数不可解析时走 `no_rule_match` 且无 `fallback_notice`。 | 工具路径参数缺失复用/补齐 clarify，至少明示缺少乘数/被乘数。 |
| P1 | E5-2 | 约束识别/降级层 | 类别词表未覆盖“编码”，`UTF-8编码` 未形成方法约束，直接落 `no_rule_match`。 | B4 类别词表补“编码”，词典外编码请求进入可见降级链；正文禁止伪装执行。 |
| P2 | E7-1 | 解析/降级层 | quicksort 数组解析不接受空数组。 | 空数组作为合法 quicksort 边界输入，返回 `[]`。 |
| P2 | E6-2 | 审计提取层 | 算术审计 equality token 未覆盖“为”族。 | 增加受限 `为` token：左侧可提取完整算式 + 白名单后缀 + 右侧纯数字。 |

## E-0 验收补答

- P-1：词典外判例 E5-1 有固定 anchor。每轮先输出 `拆解路径探测: gate=R3 action=continue method_constraints=...`，随后输出 `拆解决策: action=fallback source=builtin_tool reason=algorithm_tool_unavailable constraints=...`；no-hit 轮次也有固定 R3 anchor，例如 E5-2 输出 `method_constraints=()` 后落 `no_rule_match`。E5-2 暴露类别词表缺口：“编码”未进入 B4 类别词表。
- P-2：drill 会话按 debug 级执行；本轮未进入 LLM 拆解，所以没有 `LLM decompose 原始输出`，但日志级别已满足 B 批约定。
- C-1：生产 `PlanOrchestrator.decide(user_input)` 与侦察器一样只把当前输入传给 `PlanDecomposer`，未传主对话 history；多轮约束持续当前不具备。E3-1 第二轮显式降级来自 B4 类别通道，不是 history 生效。
- C-2：参数缺失没有结构化反问通道；有方法约束时当前会落到 `no_rule_match` 且无 `fallback_notice`，这是 E4-1 silent 的直接根因。`E4-2` 无专名未编造，普通 chat/clarify 后续呈现需 UI 链路另验。
- C-3：D-3 脚本化已由 `scripts/drill_algorithm_tools.py` 固化，E-2 后应把侦察/回归脚本改为生产注册表同源。

## 分布差异说明

- 从预期 degraded 集合挪到 silent 的是 `E5-2`：`按UTF-8编码计算"你好"的字节` 没有进入可见降级链。
- `E6-1` 不属于 degraded，而是 correct：`3乘7的结果是14` 被算术审计拦截。
- 方案外旧探针 `帮我排个序[5,2,9,1]` 与 `计算"abc"的CRC校验值` 不进入本门禁矩阵；可作为后续观察项另存。

## 裁决口径

- E8-1：E-2 先做明示降级以清 silent；完整双工具链执行记 v6 候选，不在本批铺开。
- E3-1：当前 degraded-explicit 已满足 silent 清零硬门槛；会话级约束记忆可作为体验优化顺手做，但不阻塞 E-2 闭合。

## E-2a 效果重跑（2026-08-27）

- 重跑口径：15 条预注册主判例单跑；全部规则路径，未加载模型；生产注册表同源字段用于 `PlanDecomposer` 注入。
- 三态分布：`correct=6 / degraded-explicit=6 / silent-fail=3`。新增 degraded 为 `E4-1`、`E5-2`、`E8-1`；保留 silent 为 `E1-1`、`E6-2`、`E7-1`。
- E4-1 notice 原文：`已识别到指定方法，但缺少执行所需参数；请补充完整输入后我再按该方法处理。`
- E8-1 事件流：`tool/call` 仍在场，参数为 `algorithm_booth {"multiplicand": 3, "multiplier": 7}`；执行首段保留，未整体拒绝。
- E8-1 notice 原文：`已执行可解析的首段算法请求；检测到后续复合计算片段，请分步提交以避免静默丢失。`
- E7-1 口径：当前触发泛化缺参 notice，但输入已含空数组字面量；该 notice 未说明“空数组边界”，按内容质量仍归 `silent-fail`，留给 E-2b 修成 `correct`。
- 第 3 层口径：暂未形成独立合成判例，按 §7.2 降级为占位并记 v6 观察项；负控闲聊 `今天天气不错` 已由单测锁定零 notice。

## E-2b 效果重跑（2026-08-27）

- 重跑口径：15 条预注册主判例单跑；全部规则/工具/审计确定性路径，未加载模型。
- schema 前置：生产 `algorithm_quicksort` manifest 仅声明 `values` 为 integer array，无 `minItems>=1` 护栏；放开空数组提取不会被 schema 二次弹回。
- 三态分布：`correct=9 / degraded-explicit=6 / silent-fail=0`。新增 correct 为 `E1-1`、`E6-2`、`E7-1`；既有 9 条不回归，`E3-1` 未做顺手记忆修复，仍为 degraded。
- E1-1 事件层：`tool/call` 参数为 `algorithm_booth {"multiplicand": -3, "multiplier": 7}`；工具结果 `result=-21`，中文负号没有再丢失。
- E6-2 审计层：`3乘7的积为14` 被算术审计提取为错误断言，期望值 `21`，镜像 E6-1 的拦截链路。
- E7-1 事件层：`tool/call` 参数为 `algorithm_quicksort {"values": []}`；工具结果 `[]`，空数组进入执行层并正确返回。
- E8-1 非回归：仍执行首段 `algorithm_booth {"multiplicand": 3, "multiplier": 7}` 并保留复合片段 notice，未整体拒绝。
