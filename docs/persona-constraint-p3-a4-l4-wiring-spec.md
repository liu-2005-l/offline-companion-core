# P3-A4 L4 retry/fallback 基线接线规格

版本：v1.0（实现闭合稿）

状态：已闭合；A5 总闭合已完成

上游：`docs/persona-constraint-p1-spec.md`、`docs/persona-constraint-p3-wiring-spec-draft.md`、`docs/persona-constraint-p3-a-replan-draft.md`

## 0. 范围

A4 只为进入 `PersonaSessionCore` 的本地模型候选接通 P1 冻结三分区扫描与 `direct/retry/fallback/observe` 动作链：

- `identity_cliff`、`capability_and_fact_denial`：最多一次 L4 retry，仍命中则确定性 fallback；
- `user_attack`：`observe_only`，正文原样放行并记录 warning；
- 当前发布 manifest 下的 `validated_anchor` 会话启用；历史或未验证人格保持 A3 之前的行为；
- 安全固定回复、Consent、确定性身份回复、任务结果和错误码不进入模型候选扫描链，继续逐字节透传。

不做：检测模式扩域、模型分类器、4-gram 重校、跨轮检测、后置 `set_style_strength_low`，均保留给 W3；债务③“隐藏较弱者”不进入 A4。

## 1. 可信资产

`configs/persona_constraint_l4_patterns.yaml` 作为第八源加入发布链：

`PERSONA_CONSTRAINT_MANIFEST_SHA256 → persona_constraint_corpus.yaml → l4_patterns SHA-256`

运行时只从已完成整链校验的 `PersonaConstraintAssets.source_payloads["l4_patterns"]` 构造只读策略。三分区名称与动作必须精确等于 P1 冻结值；缺失、增删分区或动作漂移均拒绝启动。

该文件是 P1 已冻结的 10 族 50 近邻对资产直接纳管，A4 不增删或重写模式；P1 的 50/50 召回、0/50 误报 fixture 继续作为内容基线。

## 2. 纯判定

`core/persona_constraint/l4.py` 复用共享 `scan_l4()`，不复制正则：

1. 无命中 → `direct`；
2. 身份断崖或能力/事实否认 → `retry`；
3. 用户攻击 → `observe`；
4. `display_name` 在场只放行通用 AI 自称族，不放行能力否认与用户攻击。

纯判定不产生事件、不写库、不调用模型。

## 3. 动作顺序

单次候选按固定顺序处理：

1. 模型生成；
2. 既有算术审计及其最多一次 retry；
3. L4 首次扫描；
4. `direct/observe` 立即形成唯一可放行正文；
5. `retry` 使用“准确优先 + 人格内诚实 + 能力边界”一次性提醒重新生成；
6. L4 retry 候选重新经过当前 L3 组装、算术审计（禁止再次算术 retry）与 L4 扫描；
7. 二次仍命中 retry 分区时丢弃两份模型候选，按首次命中分区返回确定性 fallback。

L4 不递归；一次动作链最多执行一次 L4 retry。初次算术 retry 与 L4 retry 是两条独立的有界槽位。

fallback 不复用 A2 T24 的 `constraint_config_fallback`：后者表达“人格配置未生效并保持原会话”，与“候选违反 L4 边界”语义不同。A4 的两条分区文案保持代码内确定性常量，并通过禁用词、L4 自扫描、短前缀复制、绝对承诺与内部机制泄漏五项审计。

债务结清：A5 选择迁入既有 `persona_constraint_reply_copy.yaml` 的独立 `l4_fallback_copy` 段并纳入第六源哈希链，不新增第九源，也不修改 P1 L4 patterns 冻结字节。

A5 挂账结清：L4 retry 候选重新经过 L3 时复用原轮不可变 `PersonaTurnSignals` 与 emotion confidence，不重新分类同轮模型输出。

## 4. 流式与持久化

- validated 会话的 SSE 保留传输协议，但后端 token 先在 B 层缓冲；
- 只有完成算术审计与 L4 动作链后的最终正文才按固定字符窗口回放；
- 首次失败候选不得出现在 SSE token、assistant message、记忆抽取或语义事件输入中；
- 客户端在安全回放阶段断开时，只允许保存已放行正文的 partial；
- 未验证或不受管会话继续即时转发原 token，A4 不扩大其行为面。
- 桌面端从请求发出起保持 loading，收到首个安全 token、done 或 error 后才结束；固定窗口回放继续使用既有 token 事件，前端无需特殊渲染分支；
- 缓冲期模型异常或 L4 运行时异常均 fail-close：缓冲候选不进入 SSE 或消息库，HTTP 返回固定可见失败文案，并以 `error` assistant message 留档；
- 发布态 patterns 缺失、篡改或结构漂移在启动期 fail-close，拒绝加载，不退化为无扫描放行。

### 4.1 与流式卡片 B2 的边界

A4 是 validated 会话“审计后回放”的定向例外；普通会话仍遵守“后端不设人工窗口，token 到即推”。B2 若要求 validated 会话恢复真流，必须先提供可证明等价的安全增量扫描或重构方案，不能直接绕过缓冲恢复 raw token 即时输出；否则沿用 A4 回放协议，无需重做前端 SSE 消费层。

## 5. Trace

`PersonaL4Trace` 固定记录：

- `enabled/buffered/outcome`；
- 首次与 retry 的 `zone/family`；
- `retry_taken`；
- `observe` 或 retry 耗尽 warning。

同步结果、流式 done 事件与 assistant message meta 使用同一 DTO 投影，最终态可区分 `bypass/direct/retry/fallback/observe`。

## 6. 验收

1. [x] 三分区纯判定与 display name 例外；
2. [x] 第八源发布常量真实链与篡改拒绝；
3. [x] direct 零重试；
4. [x] observe 原文放行 + warning；
5. [x] retry 首候选不可见、第二候选放行；
6. [x] retry 耗尽后确定性 fallback；该无算术重试判例中模型调用不超过两次；
7. [x] L4 retry 重新经过 L3 与算术审计且不递归；
8. [x] validated SSE 缓冲后放行，坏 token 零泄漏；
9. [x] 非受管 SSE 保持即时 token 行为；
10. [x] 保护区确定性身份回复逐字节透传；
11. [x] 消息库仅保存放行正文并带完整 L4 trace；
12. [x] HTTP 原始 SSE 字节中不存在失败候选，固定窗口回放可由现有前端逐 token 消费；
13. [x] 缓冲期模型失败与 L4 运行时失败均 fail-close，并返回可见错误终态；
14. [x] 两条确定性 fallback 文案通过五项质量审计；
15. [x] P1 L4 模式文件除行为门线外另有冻结 SHA-256 字节锚；
16. [x] A4 专测 `15 passed`，受影响链 `147 passed`，全量 `1443 passed, 3 skipped`，变更 Python 文件 Ruff 全绿。
