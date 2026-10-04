# W3-P2-2 终态报告

> **状态**：失败裁决 + 降级处置完成（**非达标闭合**）｜冻结验收线未改动｜guard 实现零触碰（自 85ece90 起未改）
> **裁决时间**：2026-10-04 12:50（选项 3 拍板）
> **本报告性质**：终稿。§1.3 冻结验收原文、§6 盲评结果与归因补钉均已回填并通过终审

---

## 0. 终态摘要

P2-2 复测批以**失败裁决**终态闭合：

- 全局 gate（b)② 通过：A/B 聚合均 **0.011826 ≤ 0.0368**，三 seed 0.015477 / 0.020000 / 0。
- 原始动机红点修复：W2 B seed42 M09-M10 具体红点生成路径复现并被修复（0.243902 → 0.016667 direct）。
- 局部验收行 (b)① **失败**：4 个 validation 触发未达“retry 后 <0.02 且转 direct”。
- 盲评 gate **失败**：B 臂 repaired 1 / pre-fix 0 / 平手 24，具体红点改善且整体不劣化；A 臂 repaired 10 / pre-fix 14 / 平手 1，S16-S18 三席一致判 pre-fix。A 的广泛差异经构造回源归为跨批来源混杂，不归因于 guard 副作用，但预注册产品级 gate 不因此移动。
- 归因三查确认 runner 干净、生成级复测，失败结构三层化：**检测层 OK / retry 修复层失败 / fallback 兜底层 OK**。
- 因果表 §2 降级审查完成，拍板**选项 3：降级记档**。guard 保留上主干，validation 场景 retry 不泛化记为已知边界。

**对既有闭合状态的影响**：无。P2-1a（46ce3a3）、P2-1b（85ece90）闭合状态不动，本失败仅终止于 P2-2 复测批。

---

## 1. 复测结果与验收行判定

### 1.1 gate 结果

| 臂 | seed 分数 | 聚合 | 阈值 | 判定 |
| --- | --- | ---: | ---: | --- |
| A | 0.015477 / 0.020000 / 0 | 0.011826 | ≤ 0.0368 | ✓ |
| B | 与 A 完全相同 | 0.011826 | ≤ 0.0368 | ✓ |

无高分未触发校准缺口。

### 1.2 六个触发（A/B 各三条，逐项相同）

| # | 臂 × seed × 场景 | 首扫 | 复检 | 处置 | retry 成效 |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | A seed42 M09 | 0.243902 | 0.016667 | direct | **成功**（唯一） |
| 2 | A seed42 V05 | 0.090909 | 0.425532 | fallback | 失败，分数反升 ×4.7 |
| 3 | A seed1337 V01 | 0.216867 | 0.246575 | fallback | 失败，分数反升 |
| 4–6 | B 三条与 A 完全相同 | — | — | — | — |

锚：`artifacts/persona_expression/w3_p2_2_trigger_samples.json:10`、`:95`。

A/B 逐项相同的机制：非身份场景两臂实际 prompt 相同（见 §2.2），同 seed 下确定性生成必然同文本同分数——非污染、非回放。

### 1.3 验收行判定

冻结原文（`docs/w3-p2-causality-table-draft.md:103`）：

> 局部 `<0.02` 只约束首扫实际触发 retry 的 pair/seed；retry 后必须 `<0.02` 且复检转为 direct；

判定：4 个 validation 触发（V05 seed42、V01 seed1337、B 同）均未满足“<0.02 且转 direct”，**验收行 (b)① 失败**。冻结验收线原文不改，不重新归类缺口。

专项验证：5 passed；Ruff 无缓存模式通过。

---

## 2. 归因三查（runner 有效性）

三查结论：**runner 干净、生成级复测**。失败归因于 guard 修复层本身，不归因于跑测环境。

### 2.1 查一：输入来源 = 生成级，非归档回放

- runner 只读用户输入 fixture：`fixtures/persona_expression/w1_cases.json:524` 与 `fixtures/persona_expression/w3_p2_2_validation_cases.json`。
- 每 case 新建隔离会话，逐轮调用真实 `core.assemble_reply()`：`scripts/run_w3_p2_repetition_retest.py:98`、`:127`。
- M09 的 P2 R1 与 W2 B seed42 R1 字节相同系**确定性生成复现**（同输入 + 同 seed + 同 prompt + 同模型 → 同输出），非回放；retry 后最终 R2 为新文本（SHA c0f080… → f2a8d1…）。
- 0.243902 与 W2 B seed42 归档值精确一致，同属确定性生成复现，不构成回放证据。

### 2.2 查二：A/B 同文本有确定解释，非 config 注入失效

- 两臂 config 快照正确：`identity_near_prompt_enabled` A=false / B=true，两臂 guard 均开启：`artifacts/persona_expression/w3_p2_2_ab_matrix.json:26`、`:7750`。
- 两臂共用同一 style block；唯一差异为身份近端提醒，且仅在 `is_identity_intent()` 命中时注入：`src/offline_companion/core/persona_session/session.py:806`。
- M09、V01、V05 均非身份意图 → 实际 prompt 相同 → 同 seed 同文本为预期结果。
- 机械旁证：每 seed 原矩阵 A/B 39/40 回复相同、validation 6/6 相同，唯一差异为身份题 S09——证明配置确实生效，仅目标场景未激活 B 专属分支。

### 2.3 查三：版本与 backend

- 产物记录 commit=85ece90、真实 GGUF 路径、guard enabled：`artifacts/persona_expression/w3_p2_2_ab_matrix.json:4`。
- commit 时间 00:15:20，六个 checkpoint 在 00:33:55–00:43:12 顺序生成（改码时间早于跑测时间）。
- runner 非 echo 模式调用 `_build_backend(... seed=seed)`：`scripts/run_w3_p2_repetition_retest.py:188`；echo 输出必含 `[w1-echo …]`，现有回复均不符合该形态。

---

## 3. 失败结构三层化

| 层 | 判定 | 证据 |
| --- | --- | --- |
| 检测层（guard 首扫拦截） | **OK** | V01/V05 首扫均被拦截（0.216867 / 0.090909 全部触发处置） |
| 修复层（retry 生成） | **失败** | validation 触发复检分数反升（0.425532 / 0.246575）；M09 对照成功（0.016667） |
| 兜底层（fallback） | **OK** | 红回复未流出，全局 gate 保持绿色 |

**关键事实记档**：

1. M09 retry 成功 vs validation 4/4 全败——场景级系统性差异，非随机方差（2 validation 场景 × 2 臂 = 4/4 全败 vs M09 成功）。
2. **首扫分数不能预测 retry 成败**：V05 first 0.090909（六触发中最低）复检反升最惨；M09 first 0.243902（最高）反而修复。分数分层派发 fallback 的方案因此被否（见 §4）。
3. 机制解释（如“否定式指令锚定效应”）当前**无实验支撑，不写入结论**，仅记现象。

---

## 4. 降级处置（因果表 §2）

### 4.1 选项过秤

| 选项 | 裁决 | 理由 |
| --- | --- | --- |
| a) retry instruction 强化 | **否** | 修的是 1.5B 生成能力缺口（非流程缺口），复检分数反升 ×4.7 非措辞可救；每轮尝试需生成级复测验证，成本 > 预期收益 |
| b) validation 场景 fallback-only | **否（当前）** | 场景分派样本量仅 2（V01/V05），撑不起场景白名单——过拟合风险；场景分类器为新判定逻辑需另行校准；且首扫分数不能预测成败（§3 事实 2），无可靠分派特征 |
| c) 降级记档 | **✓ 拍板** | 任务本体用户可见面已交付；retry 有真实成功案例（M09）；fallback 保证流出面安全 |

### 4.2 拍板结果（2026-10-04）

- **P2-2 终态 = 失败裁决 + 降级处置完成**，不得写成达标闭合；冻结验收线不改。
- **guard 保留**：检测层与 fallback 层有效。
- **已知边界显式记档**：validation 类场景 retry 不泛化，依赖 fallback 阻止红文本流出。边界不静默。
- retry 修复层现状保留，不做 instruction 强化，不做场景分派。

### 4.3 上主干口径

guard enabled 随 W3 收口批上主干；CHANGELOG / 文档记“跨轮复读门：记忆跨轮场景修复有效（M09 0.243902→0.016667 direct），validation 类触发依赖 fallback 兜底（retry 不泛化）”。

---

## 5. A/B 同构性核对与 W2 叙事修正

- 臂定义实质同构：`scripts/run_persona_expression_w2.py:90` vs `scripts/run_w3_p2_repetition_retest.py:81`，P2-2 仅额外开启 guard。
- W2 时代 B 身份提醒同样仅身份意图生效，M09 不命中——**不能推断 W2 A/B 的 M09 prompt 存在差异**。
- W2 A/B 实际分日生成（A 08-30 / B 08-31 且 resume=true），历史 checkpoint 未绑定 provenance → W2 A/B 分数差值**归为跨批运行差异，不可归因**。
- **W2 叙事修正**：“B 主红 M09-M10”不外推为臂差异证据；W2 归档的 A/B 差异不可作为后续论据引用。

**采信叙事口径**：“P2-2 在当前冻结配置下复现并修复了 W2 B seed42 M09-M10 的具体红点生成路径”，不泛称“修复 B 臂”。

**盲包构造归因补钉**：盲包按“同 arm、同 seed、同 case”的修复前后流出文本配对，不是 A/B 两臂横比。A 系列取 W2 A seed42（2026-08-30，commit 2217db8）对 P2-2 A seed42（2026-10-04，commit 85ece90）；B 系列取 W2 B seed42（2026-08-31，`resume=true`，commit 2217db8）对 P2-2 B seed42。S+M 等值计数为 pre-A/post-A 1/25、pre-B/post-B 24/25、post-A/post-B 24/25；P2-2 原矩阵中 A 臂仅 M09-M10 首扫触发 guard，其余 23 个 A 非平手样本均未触发。故 A/B 盲评不对称的直接解释是**历史 pre-A/pre-B 分日生成且 provenance 不闭合造成的跨批构造混杂**；它足以使产品级“不劣化”gate 失败，但不能作为 guard 导致 A 臂文本变差的因果证据。

---

## 6. 盲评（已完成）

### 6.1 封包与评审有效性

- 封包：50 对，协议要求至少 3 名有效评审，`artifacts/persona_expression/w3_p2_2_blind_review_protocol.json:4`。
- Packet SHA-256 复核：`0C14789E68E7F3753F8AF0D2FEF61D26AD4E5552E6FF4BF51C48F2FCFB1F8B04`，与协议一致。
- Key SHA-256 复核：`7D8B8398EF372D21ABAC6FBDA2B11D15725227104B8DD5E40684D406B505CEE0`，与协议一致；三席完成且 Packet 哈希复核后才解封。
- 三席：Sagan（无上下文 AI）、Ramanujan（无上下文 AI）、prompt-side（对话上下文在场并显式披露 M09-M10 污染风险）。三份均为 50 条、顺序与 Packet 一致、ID 唯一、值域合法、reason 非空。
- prompt-side 原始分布：A 10 / B 13 / 平手 27；其 A-M09-M10 与 B-M09-M10 两条按披露降权，以两席无上下文结果作为主判。

### 6.2 解盲聚合

| 范围 | repaired 胜 | pre-fix 胜 | 平手 | 无共识 |
| --- | ---: | ---: | ---: | ---: |
| 全 50 对（三席多数决） | 11 | 14 | 25 | 0 |
| A 臂 | 10 | 14 | 1 | 0 |
| B 臂 | 1 | 0 | 24 | 0 |
| A 臂（A-M09-M10 污染调整后） | 10 | 13 | 1 | 1 |

验收相关分面：

- A 单轮：repaired 10 / pre-fix 12 / 平手 1，未满足“repaired outputs must not lose to their pre-fix arm overall”。
- A S16-S18：三席一致选择 pre-fix，双臂多轮不失守条件中的 A 侧失败。
- B S16-S18：三席一致平手，不劣化。
- B M09-M10：三席一致选择 repaired；结合机械值 0.243902 → 0.016667 direct，形成数字面 + 人工面双证据。
- A M09-M10：三席原始多数为 pre-fix；剔除 prompt-side 污染席后两席无上下文 1:1，记无共识，不用于正负结论。

### 6.3 盲评裁决与归因

盲评 gate 判定为**失败**：A 单轮整体掉分且 A S16-S18 失守；冻结验收线不移动。B 臂则达成“不劣化 + 具体红点改善”，是 P2-2 最硬的正面成果。

其中 B 系列是本包唯一干净的修复前后对照：pre-B/post-B 24/25 逐案相同，唯一非平手项 B M09-M10 获三席一致 repaired 胜；A M09-M10 虽处于跨批混杂对照中，方向与 B 同向。故 M09-M10 修复有效由**干净 B 对照的数字 + 人工双证据**直接确认，并由 A 同向结果提供旁证。

A/B 系列不对称不归因于 guard：封包构造器按自臂前后配对（`scripts/build_w3_p2_blind_review.py:42`），而非臂间横比；A 的广泛非平手中仅 M09-M10 实际触发 guard，其余差异来自 W2 历史 A 批与 P2-2 当前批之间的跨批生成漂移。故报告同时保留两层结论：

1. **验收层**：预注册产品级前后不劣化 gate 失败，P2-2 不得判达标闭合；
2. **因果层**：A 广泛掉分属于跨批来源混杂、不可归因，不构成 guard 对 A 臂有真实副作用的证据，不据此改变 guard 的实现或默认开关。

附带限定：漂移发生在 W2 A（2026-08-30）到 P2-2 A（2026-10-04）的代码/资产运行路径之间；本批不为追溯具体 commit 差异追加考古。W2 A 归档文本与当前 A 生成结果不得再作为可归因的直接前后对照，后续引用必须带“跨批来源混杂、不可归因”限定语。

范围外观察：B-S09 的 pre-fix/repaired 文本逐字相同，均内部复读“我不会滑向通用‘语言模型/没有性格’腔”两遍；记为既存的身份提示措辞泄漏候选，不算本批回归，后续引用前须单独回源与定级。

---

## 7. runner 补强挂账（W3 收口批）

| 项 | 内容 | 状态 |
| --- | --- | --- |
| checkpoint provenance 绑定 | checkpoint 绑定 commit / model / config 快照，杜绝跨批不可归因复发 | 挂 W3 收口批 |
| candidate capture | 保存被拒 first/retry 候选正文，支持正文级字节对照审计 | 挂 W3 收口批 |

当前不改实现、不提交。

---

## 8. commit 条件

- **前置**：本报告终审。
- **形态**：单 commit 收口——本报告（落 `docs/`）+ P2-2 runner/fixtures/产物；guard 实现零触碰由 diff 自证。
- 当前工作区未提交改动 = P2-2 复测新增物（runner + fixtures + 产物 + 本报告），guard 实现未改动。
