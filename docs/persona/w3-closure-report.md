# W3 收口报告

日期：2026-10-13
状态：收口批完成；R1 的 4-gram 红线重校继续挂 P4 roster，不宣称完成。

## 1. 结论

W3 的工程收口链已完成：P1 统一输出侧 L4 权威并退役 C 臂，P2 接入独立跨轮复读门，R0 用同代码树单变量对照验证修复方向与零外溢，C1 将 guard 以 `0.09 + gt` 默认上主干，C2a 删除历史 A/B 表达开关，C2b 与 C5 完成 evidence-first audit。

本报告不把 R0 冒充 R1。`0.0368` 仍是待 P4 判别协议与 roster 完整后处理的总 gate；本批没有移动该红线。

## 2. 原始输入对账

| W3 输入 | 终态 | 证据锚 |
| --- | --- | --- |
| 输出侧身份/机制风险覆盖 | P1 完成：L4 为单一输出侧权威，dormant C 臂退役；检测、动作和 fail-close 消费面已闭合 | `docs/w3-p1-output-gate-spec-draft.md` |
| 跨轮复读结构修复 | P2 完成工程链：检测层与 fallback 层有效；retry 对 validation 不泛化的失败保持原裁决，不改验收线 | `docs/w3-p2-2-closure-report-draft.md` |
| guard 上主干 | C1 完成：生产默认开启，阈值 `0.09`、比较符 `gt`；W2/P2 runner 继续显式钉死各自 guard 态 | `src/offline_companion/core/persona_session/expression.py:39`、`scripts/run_persona_expression_w2.py:83`、`scripts/run_w3_p2_repetition_retest.py:78` |
| A/B 表达开关退役 | C2a 完成：`style_examples_enabled` 与 `identity_near_prompt_enabled` 删除；style block 始终尝试组装，身份提醒仅由 identity intent 决定 | commit `5c07c96` |
| 身份提醒强化挂账 | C2b 以“无需进一步改动”闭合；当前树三 seed 旧特征串为零，正向自称与注入状态保持 | `docs/persona/w3-closure-c2b-c5-audit.md`、`artifacts/persona_expression/w3_closure_c2b_identity_echo_spot_check.json` |
| 4-gram 重校 | R0 完成；R1 未完成并挂 P4 roster。不得声称已确定新红线 | `artifacts/persona_expression/w3_closure_r0_guard_blind_aggregate.json`、`docs/p4-roster-kit.md` |
| R1 去向域覆盖 | C5 完成评估；两项均判“扩域，另立新批”，已有候选池锚 | `W3-C5-L4-DYNAMIC-IDENTITY`、`W3-C5-A3-GENERATED-REMINDER-LINT` |

## 3. R0 结构证据

R0 运行产物绑定代码树 `19cbef02b81a7d4fb65cb191e3e89d273aae6916`。W2 runner 的 A/B 均显式 guard-off，P2 runner 的 B 臂显式 guard-on；终态 `.audit.json` 以独立 `audit_schema=1` 保存逐 checkpoint commit、配置指纹与 resume history。

- guard-off 的 W2 A/B 三 seed `cross_turn_4gram_jaccard_mean` 均值为 `0.049698`。
- guard-on 的 P2 B 三 seed 均值为 `0.011826`，与 P2-2 历史值逐位复现。
- 盲审共 36 对：35 个 `single_turn_no_spill` 对三席全判 tie；唯一 `multi_turn_repair` 对 G006 三席均判 repaired 胜。
- 聚合结果为 `36/36` 符合预注册终态、偏差 `0`、`statistical_significance_claimed=false`。

这些结果证明当前单变量对照下的修复方向与单轮零外溢，不构成 4-gram 红线重校或统计显著性主张。

## 4. C1 / C2 终态

### 4.1 生产默认与开关拓扑

- `cross_turn_repetition_guard_enabled=True` 是唯一默认值翻转；运行时阈值维持 `0.09 + gt`。
- 历史 A/B 表达开关已删除；identity intent 条件、style helper、L4 路径、retry/fallback 预算与 R0 artifacts 均保留。
- 流式缓冲仅在既有 A4 审计要求或“guard 开启且 constraint assets 在场”时启用；无资产会话保持真流。完整实现期勘误见 `docs/persona/w3-closure-batch-spec-draft.md` §7.1。

### 4.2 C2b / C5

C2b 的当前树证据没有剩余红点，因此不再改提醒文案或机制。C5 则确认两个真实覆盖缺口，但二者都超出本收口批边界：动态身份一致性需要语义级运行时比较，代码生成提醒 lint 需要扩展扫描输入面与规则。候选池锚及最小契约见 `docs/CHANGELOG.md`。

## 5. 未完成项与禁止表述

- **R1 未完成**：等待 P4 roster filled 与正式判别协议后，才能裁决 `0.0368` 是否移动。
- **禁止表述**：不得把 R0 写成 R1 阈值裁决终态、新红线已确定或统计显著性验证。
- **P4 材料注意**：C2a 后 W2 历史 A/B 开关维度已经退役；未来 R1 不得把新跑的同构两臂冒充旧 A/B 语义。

## 6. 后续串行入口

W3 报告闭合触发案例库记忆链路三合一批，状态为“已触发、未实现”：

1. profile 冲突检测；
2. 语义去重校准；
3. v1.8 embedding 复用验证。

该三合一批与两个 C5 扩域候选相互独立；不得借后续批回写 W3 已冻结的 guard、R0 或 C2b 结论。

## 7. 验收对账

| 验收项 | 结果 |
| --- | --- |
| P1/P2/收口批终态逐项带证据锚 | 通过 |
| guard 上主干与 A/B 开关退役边界 | 通过 |
| C2b 三态结论落档 | 通过：无需进一步改动 |
| C5 两域三态结论与持久去向锚 | 通过：两项扩域，已进 v1.9.x 候选池 |
| R0/R1 边界 | 通过：R0 完成，R1 明示挂 P4 roster |
| 红线与统计措辞 | 通过：未移动 `0.0368`，未声明显著性 |
| 记忆链路三合一触发 | 通过：已建立下一串行入口 |
