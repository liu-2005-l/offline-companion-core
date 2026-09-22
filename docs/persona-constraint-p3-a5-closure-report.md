# P3-A5 总闭合报告

版本：v1.0

状态：已闭合

上游：`docs/persona-constraint-p3-a-replan-draft.md`、`docs/persona-constraint-p3-a4-l4-wiring-spec.md`

## 1. 收口裁决

### 1.1 L4 fallback 发布治理

两条 L4 确定性 fallback 不保留代码常量例外，迁入既有冻结源
`configs/persona_constraint_reply_copy.yaml` 的独立 `l4_fallback_copy` 段。该方案不新增第九源，继续复用
`发布常量 → corpus manifest → reply_copy SHA-256` 信任链；运行时只从已完成整链校验的
`PersonaConstraintAssets.source_payloads["reply_copy"]` 构造只读模板。

P1 冻结 `persona_constraint_l4_patterns.yaml` 不改字节，SHA-256 仍为
`02b1eca439244429e4217da621f7cb3e7608e75fe8fbbafcf96a11111a711647`，因此 P1 的模式 fixture
与原召回/误报结论不需要重校。

### 1.2 L4 retry 的 L3 confidence

L4 retry 复用原轮不可变 `PersonaTurnSignals` 实例及其 emotion confidence，不重新调用情绪分类器。
原因是 retry 属于同一轮候选纠偏，不是新的用户输入；重新分类模型输出既会改变信号物理含义，也会引入同轮漂移。
判例同时断言首次生成与 retry 两次 `_apply_l3()` 收到同一对象、confidence 保持 `0.45`，且 retry prompt
以前一份 L3 prompt 为前缀，仅追加一次性 L4 reminder。

## 2. 闭合门

1. P1/P2/P3 persona fixture 全集：`191 passed`；
2. A1-A4 运行时受影响链：`189 passed`；
3. 全仓 pytest：`1444 passed, 3 skipped`；
4. 变更 Python 文件 Ruff：全绿；
5. `git diff --check`：通过。

## 3. A1-A5 终态

| 批次 | 终态 | 已知边界 |
| --- | --- | --- |
| A1/A1.1 | canonical session、快照四列、原子切换、真实进程恢复与注册表重绑已闭合 | 无隐式远端状态；历史快照保持冻结 |
| A2 | 完整根、五预设、L1 组装、v15 traits 保全、15 条文案与写旁路清零已闭合 | 自定义人格保持未验证，不自动启用约束 |
| A3 | L3 纯谓词、三审计信号、共享 lint 与逐轮临时样本切换已闭合 | 后置 `set_style_strength_low` 待 W3 |
| A4 | L4 direct/retry/fallback/observe、validated SSE 缓冲与 fail-close 已闭合 | 真流恢复必须先有等价增量安全扫描 |
| A5 | fixture 全量门、fallback 发布链与 confidence 复用裁决已闭合 | L3/L4 模型效果仍待 P4 |

显式保留项：L2 维持 `no_effect_observed_within_preregistered_grid` 不采用；单对失败隐藏策略在 P4 verdict
前保持 dormant；P1/P2 原始 GGUF 实验不在 A5 重跑范围；流式卡片 B0-B4 不得把 A4 防线降级。

## 4. 结论

门禁全部通过，P3-A 的持久化基座、L1 组装、L3 逐轮信号和 L4 输出防线整体闭合。L2 保持
`no_effect_observed_within_preregistered_grid` 不采用结论；L3/L4 当前证明工程接线与 trace 确定性，模型效果仍待 P4。
后续检测扩域、
低延迟增量扫描与 `set_style_strength_low` 仍归 W3；流式卡片从 B0 契约冻结开始，不得旁路 A4 缓冲防线。
