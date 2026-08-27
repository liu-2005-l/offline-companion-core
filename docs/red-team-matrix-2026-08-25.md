# Batch E-1 红队侦察矩阵（2026-08-27）

## 口径说明

- 本轮只做侦察，不做修复；产物用于 E-2 对拍“修复前 → 修复后”。
- 本轮 harness 覆盖 `PlanDecomposer`、确定性 Tool 执行、算术审计与 Tool 事件层；`NotDecomposableResult` 后续普通 chat 未调用，因此降级内容以 `fallback_notice` 与拆解决策为准。
- manifest 注册信息为一次性侦察脚本手抄复刻 `bootstrap.py` 字段；E-2 后若焙成回归常量，必须改为 import/复用生产注册表同源，避免 D-1 类漂移复发。
- 日志级别按 E-0 P-2 开 `debug`，LLM 原始输出可追；本轮所有主判例均未进入 LLM 拆解，因此无 LLM 原始输出正文。
- 本地工作区未找到 `docs/red-team-batch-e-design.md` 同步件；本矩阵先按 v6 七族描述与侦察脚本事实记档，待方案原文落仓库后需再做一次 ID 对齐审阅。
- 临时原始 JSON：`.tmp_e1_scout.json`。该文件不作为仓库事实源，本文档为本轮矩阵记档。

## 汇总

| 集合 | 条数 | correct | degraded-explicit | silent-fail |
|---|---:|---:|---:|---:|
| 主判例 | 15 | 5 | 4 | 6 |
| 附加探针 | 2 | 1 | 1 | 0 |
| 合计 | 17 | 6 | 5 | 6 |

## 主判例矩阵

| ID | 七族 | 输入原文 | 三态 | 日志 / 事件依据 | 结论 |
|---|---|---|---|---|---|
| E1-1 | 负数 | `用booth算法计算负三乘七` | silent-fail | R3 命中 `('booth算法',)`；builtin `algorithm_booth > chat`；事件 `tool/call, tool/result` | 解析层：中文负号丢失，工具实际执行 `3 × 7 = 21`，应为 `-21`。 |
| E1-2 | 负数 | `用欧几里得算法求-48和18的最大公约数` | correct | R3 命中 `('欧几里得算法',)`；builtin `algorithm_gcd > chat`；事件 `tool/call, tool/result` | GCD 负数 abs 语义正确，结果 `6`。 |
| E2-1 | 大数 | `按照booth算法计算77乘88` | correct | R3 命中 `('booth算法',)`；builtin `algorithm_booth > chat`；事件 `tool/call, tool/result` | Booth 大数路径正确，结果 `6776`。 |
| E3-1 | 双工具链 | `先按booth算法算3乘7再乘2` | silent-fail | R3 命中 `('booth算法',)`；builtin `algorithm_booth > chat`；事件 `tool/call, tool/result` | 拆解/路由层：只执行第一段 `3 × 7 = 21`，静默丢失 `再乘2`，应交付 `42`。 |
| E4-1 | 参数缺失 | `用booth算法算一下` | silent-fail | R3 命中 `('booth算法',)`；fallback `no_rule_match`；无事件 | 路由/降级层：有方法约束但无工具计划且无 `fallback_notice`，没有明示缺少乘数/被乘数。 |
| E4-2 | 参数缺失 | `排个序` | degraded-explicit | R3 无约束；fallback `no_rule_match`；无事件 | 未编造参数、未生成假计划；但无 `fallback_notice`，后续 UI 表述质量仍需 E-2 留意。 |
| E4-3 | 参数缺失 | `按快速排序排` | silent-fail | R3 命中 `('快速排序',)`；fallback `no_rule_match`；无事件 | 路由/降级层：有方法约束但缺数组时无明示，需提示“需要提供数组”。 |
| E5-1a | 多轮指代 | `按booth算法算3乘7` | correct | R3 命中 `('booth算法',)`；builtin `algorithm_booth > chat`；事件 `tool/call, tool/result` | 第一轮金路径正确，结果 `21`。 |
| E5-1b | 多轮指代 | `再用刚才的算法算5乘8` | degraded-explicit | R3 命中 `('刚才的算法',)`；fallback `algorithm_tool_unavailable`；无事件 | 侦察器裸喂单轮输入；当前生产装配中 `PlanDecomposer.decide()` 同样只接收 `user_input`，因此此结果可信：未沿用上一轮 `booth`，但 B4 类别通道显式降级。 |
| E6-1 | 快排边界 | `按快速排序排[]` | silent-fail | R3 命中 `('快速排序',)`；fallback `no_rule_match`；无事件 | 解析/降级层：空数组未解析到 quicksort，也无明示；应返回 `[]` 或明确边界。 |
| E6-2 | 快排边界 | `按快速排序排[5]` | correct | R3 命中 `('快速排序',)`；builtin `algorithm_quicksort > chat`；事件 `tool/call, tool/result` | 单元素 quicksort 正确返回 `[5]`。 |
| E7-1 | 降级链内容 | `按照MD5算法计算这段文字的哈希` | degraded-explicit | R3 命中 `('md5算法',)`；fallback `algorithm_tool_unavailable`；无事件 | 可见降级且未编造 hash；但 `fallback_notice` 未点名 `MD5`。 |
| E7-2 | 降级链内容 | `按照MD5算法计算"abc"的哈希` | degraded-explicit | R3 命中 `('md5算法',)`；fallback `algorithm_tool_unavailable`；无事件 | 可见降级且未编造 32 位 hex；但 `fallback_notice` 未点名 `MD5`。 |
| E8-1 | 措辞变异 | `3乘7的结果是14` | correct | 算术审计 `extracted=1 failures=1 skipped=none` | “的结果是”族已拦截。 |
| E8-2 | 措辞变异 | `3乘7的积为14` | silent-fail | 算术审计 `extracted=0 failures=0 skipped=missing_equality` | 审计提取层：“为”族未进 equality token，错误断言漏检。 |

## 附加探针

| ID | 探针 | 输入原文 | 三态 | 加入理由 | 结论 |
|---|---|---|---|---|---|
| E9-1 | 裸意图泛化 | `帮我排个序[5,2,9,1]` | degraded-explicit | 探测无“快速排序”专名时是否误编步骤或能泛化路由。 | 当前 fallback `no_rule_match`，未编造执行；可作为后续 trigger 词表候选，不阻塞 E-2 主判据。 |
| E10-1 | CRC 金路径回归 | `计算"abc"的CRC校验值` | correct | 探测 D 批 CRC 裸触发词在 E 批侦察环境中是否仍稳定。 | `algorithm_crc32 > chat`，事件 `tool/call, tool/result`，结果 `0x352441C2`。 |

## Silent 清单与 E-2 优先级

| 优先级 | 对应判例 | 根因定位 | 修复方向 |
|---:|---|---|---|
| P1 | E1-1 | 中文负号 `负三` 被整数解析吃成 `3`，方法和数值都看似成功。 | 扩展中文负数解析，Booth 参数解析前保留符号。 |
| P1 | E3-1 | `_booth_plan` 只解析首个乘法表达式，复合算式尾段静默丢失。 | 复合链路识别；至少显式降级，理想为 `booth → calculator` 双工具链。 |
| P1 | E4-1 / E4-3 | 有方法约束但参数不可解析时走 `no_rule_match`，且无 `fallback_notice`。 | 方法约束存在 + 工具参数缺失时返回明示缺参提示。 |
| P2 | E6-1 | quicksort 数组解析不接受空数组。 | 空数组作为合法 quicksort 边界输入。 |
| P2 | E8-2 | 算术审计 equality token 未覆盖“为”族。 | 增加受限 `为` token：左侧可提取完整算式 + 白名单后缀 + 右侧纯数字。 |

## E-0 验收补答

- P-1：词典外判例 E7-1/E7-2 有固定 anchor。每轮先输出 `拆解路径探测: gate=R3 action=continue method_constraints=...`，随后输出 `拆解决策: action=fallback source=builtin_tool reason=algorithm_tool_unavailable constraints=...`；命中与 no-hit 都可从这两行回答。
- P-2：drill 会话按 debug 级执行；本轮未进入 LLM 拆解，所以没有 `LLM decompose 原始输出`，但日志级别已满足 B 批约定。
- C-1：生产 `PlanOrchestrator.decide(user_input)` 与侦察器一样只把当前输入传给 `PlanDecomposer`，未传主对话 history；多轮约束持续当前不具备。
- C-2：参数缺失没有结构化反问通道；有方法约束时当前会落到 `no_rule_match` 且无 `fallback_notice`，这是 E4-1/E4-3 silent 的直接根因。
- C-3：D-3 脚本化已由 `scripts/drill_algorithm_tools.py` 固化，E-2 后应把侦察/回归脚本改为生产注册表同源。

## 非 silent 但需注意

- E5-1b：A-3 “无 history”仍成立；本轮不是沿用上一轮算法，而是把“刚才的算法”识别成未知算法后显式降级。若产品目标是多轮约束持续，E-2 仍需加最小会话级约束记忆。
- E7-1 / E7-2：降级链未编造内容，合格；但提示未点名 `MD5`，可在 E-2 优化为“无法按 MD5 分步执行”。
- E4-2 / E9-1：无方法约束时 `no_rule_match` 未必有用户可见文案；是否算 degraded 依赖 UI/Auto 后续呈现，E-2 可只修有明确方法约束的缺参路径。
