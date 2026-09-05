# P3-0 L2 标定判定线规格

版本：v0.2（repo trace 与统计功效修订稿，跑实验前预注册）  
状态：待 TA 终裁；判定线冻结后才允许生成筛选数据  
上游：`docs/persona-constraint-p3-0-numeric-anchor-spec-draft.md`、
`configs/persona_constraint_dimension_corpus.yaml`、`configs/persona_constraint_lexicon.yaml`

## 0. 定位与 v0.1 反证

本规格定义“什么数据有资格写入 L2 数值包”。它必须先于实验结果冻结，防止看完结果再选指标、比较族或门线。

v0.1 有四处不能直接执行：

1. `320/15≈21` 的分配不成立。mid 五格固定 baseline，不参加 delta 选择；真实实验是 10 个 low/high 目标，
   每目标 7 个非 baseline 候选，每候选只有 4 个配对观察；
2. `n=4` 时即使 `4/4`，单侧二项尾概率仍为 `0.0625`，连未校正 `0.05` 都过不了。320 轮只能做候选筛选，
   不能同时承担显著性确认；
3. P1 `persona_constraint_lexicon.yaml` 的 `expression_cues` 按温柔/暴躁/可靠/甜美/可爱组织，不是 OCEAN
   五维三档量表，不能零成本承担 O/C/E/A/N 的主评分；
4. “半档等效 delta”没有定义测量尺度，而且采样参数线性叠加不意味着语言输出分数线性，不能拿它做组合 gate。

因此采用**320 轮筛选 + 独立确认集 + 80 轮组合工程复验**。筛选数据只选候选，确认数据才做统计推断；两者
不得复用 prompt、seed 或输出。

## 1. 评分对象与方向性

### 1.1 主判据

主判据是同 prompt、同 seed 下“候选参数输出 vs baseline 输出”的盲化配对判断。评审只看到目标维度档位的
冻结语义与随机左右顺序，不看到参数、delta 符号、seed、文件名或候选身份。

目标语义直接来自 P2 冻结 `dimension_units` 的 `intent + signatures`，不另造抽象人格词频：

| 维度 | low 目标 | high 目标 |
| --- | --- | --- |
| O | 熟悉、具体、已验证路径 | 新颖联系、替代视角、保留执行边界 |
| C | 灵活、低仪式感但不降事实质量 | 可验证行动、证据与承诺闭环 |
| E | 克制内敛、少主动延展 | 主动互动、自然邀请展开但不抢话 |
| A | 直接独立、攻击问题不攻击用户 | 温和支持、先承接再建议、不替用户决定 |
| N | 稳定、少担忧措辞 | 对风险更敏感、审慎提醒但不放大恐慌 |

`A-high` 不定义为“顺从”，`N-high` 不定义为“担忧词越多越好”。显著但偏离上述冻结语义仍判失败。

### 1.2 P1 词表的正确角色

- `forbidden_semantic_families` 继续作为禁用硬 gate；
- 四个 style trait 的 `expression_cues/rhythm` 只作五标定点组合报告的诊断列；
- 可靠人格继续走证据、纠错、不装懂与承诺兑现行为判据；
- 不允许用命中词数量替代 OCEAN 主判断，避免把重复口癖、冗长输出或语料背诵误判为 delta 生效。

### 1.3 配对结果

每个 item 只产生一个二元结果：

- 候选比 baseline 更符合目标档位：success；
- baseline 更符合、不可区分、无多数或两边都不合格：failure。

硬 gate 红样本直接记 candidate failure，并保留具体错误码；不得因风格方向明显而豁免。

## 2. 第一阶段：320 轮候选筛选

### 2.1 实验单元

五维各测 low/high，共 10 个目标格。每格包含 7 个非 baseline candidate arms 与 1 个 baseline arm；
2 prompts × 2 seeds 形成每 arm 4 个输出，总量仍为：

`10 目标格 × 8 arms × 2 prompts × 2 seeds = 320`。

每个非 baseline candidate 只有 4 个 candidate-baseline 配对观察。该阶段不计算“显著通过”，不产生可写入锚的
p 值或置信结论。

### 2.2 筛选 gate

候选按以下顺序筛选：

1. 禁用语义族 `=0`；
2. L4 硬拦截区 `=0`，observe-only 单列；
3. 短前缀复制 `=0`，检测器历史正控必须命中；
4. 无空输出、截断句或异常 finish reason；
5. 盲化方向判断至少 `3/4` success，且不存在反向多数。

`3/4` 仅是工程筛选线，不得写成统计显著。

screening 使用单名 TA 盲审。选项固定为 `left/right/indistinguishable`；不可区分、平局或两侧均不合格均记
candidate failure，不从四项分母剔除。具体语义与 key 封存要求由
`fixtures/persona_constraints/p3_0_l2_screening_review_protocol.yaml` 冻结。

### 2.3 单一候选选择

每个目标格最多选一个 candidate 进入确认集。确定性排序为：

1. 先排除任一硬 gate 红的候选；
2. 在达到 `3/4` 的候选中取标准化绝对步长最小者，temperature 与 top_p 的一个网格步长都记为 `1`；
3. 步长相同时取 success 更多者；
4. 仍相同时按 `temperature` → `top_p`、负 delta → 正 delta 的固定顺序取第一项。

没有候选达到筛选线则该格直接记 `no_effect_found`。确认失败后不得回到同一筛选数据里改选第二名；若要测第二名，
必须另锚新的独立确认批。

## 3. 第二阶段：独立确认集

### 3.1 样本与生成量

每个维度建立 40 条新的独立 prompt，low/high 共用同一批 prompt。每条 prompt 只分配一个冻结 fresh seed，
不使用“同 prompt 多 seed”冒充独立 item。seed 列表、prompt 顺序与哈希必须在生成前写入 fixture。

若 10 个目标格均有候选，最大生成量为：

`5 维 × 40 prompts × (1 baseline + 1 low candidate + 1 high candidate) = 600`。

baseline 在同维 low/high 比较间复用，因此统计上有相关性；Bonferroni 不要求各检验独立。没有候选的目标格不生成
candidate 输出，但比较族分母仍固定为 10，不按结果缩小。

若 screening 后仅七格有候选，确认集固定为 280 个 pair item、最多 440 个实际生成输出。省下的 120 pair item
与 160 个生成输出全部弃用，不回填边界 arm；每格仍为 `n=40`，避免按筛选结果事后改变功效。

### 3.2 评审协议

每个配对 item 由 3 名不知道候选选择过程的评审独立判断，多数票形成 success/failure；不可区分或无多数计 failure。
评审可复用 P4 外部 roster，但本批不冒充 P4 发布盲判。评审说明、随机左右顺序和评分表在首个输出生成前冻结。

### 3.3 比较族与精确门线

- 原假设：候选相对 baseline 的目标方向胜率 `p=0.5`；
- 检验：单侧精确二项；
- family：五维 low/high 共 10 个确认检验，mid 不参加；
- family-wise alpha：`0.05`；Bonferroni 单格 alpha：`0.05/10 = 0.005`；
- 每格 `n=40` 时最低通过线：`29/40 = 72.5%`；
- 精确尾概率：`P(X>=29 | n=40,p=0.5) = 0.003213288047845708`；
- `28/40` 的尾概率为 `0.008294501687487355`，不通过本批十格校正线。

报告同时给每格原始胜率、单侧精确 p 值与 Clopper-Pearson 置信区间。统计门只看预注册的 `29/40`，不得改用
未校正结果、按维五组校正或看完数据后的 Holm 排序救线。

### 3.4 确认裁决

- 达到 `29/40` 且确认集硬 gate 全绿：候选 delta 记为 `confirmed_effective`；
- 未达到：记为 `confirmed_no_effect`，该格回填证据化 `no_change`；screening 无候选的格保持
  `screened_no_candidate`，不得升级措辞为“确认无效”；
- 显著但目标方向相反不存在“收编”路径，因为 success 已按目标方向定义；反向结果只进失败分析；
- 确认数据不得用于重新选 delta 大小或参数轴。

## 4. 五标定点组合复验

### 4.1 覆盖对象

组合复验只覆盖温柔、暴躁、可靠、甜美、可爱五个 `validated_anchor`。现有小诺、阿策、知心的 OCEAN 签名均未
命中冻结标定点，P3 v1.2 已裁为 `unvalidated_custom` 且人格约束默认关闭；把它们塞进本批会混淆支持边界。

轮次保持：`5 标定点 × 4 场景 × 2 seeds × 2 arms = 80`。每个标定点有 8 个 candidate-baseline 配对结果。

### 4.2 验收对象

采样参数层的线性是可精确断言的组合公式，不是语言输出分数的线性假设：

`final_parameter = baseline + Σ(delta_O, delta_C, delta_E, delta_A, delta_N)`。

applied-options 必须逐维、逐参数与公式完全一致。语言输出只做非线性交互 smoke：

- 全部 candidate 输出继续过禁用/L4/复制/完整性硬 gate；
- 每标定点至少 `6/8` 配对结果更符合该冻结人格，ties 计 failure；
- 该 `6/8` 是工程交互 gate，不宣称统计显著，也不替代 P4；
- 报告逐维列出单维确认方向与组合后方向，禁止只给总分掩盖某维反转。

“观测分数与线性预测相差不超过半档”删除：当前没有连续档位等效尺度，模型响应也不是线性系统。

### 4.3 超线处置

组合 gate 失败时选择**按维交互诊断与重标定**，不降级成“实际组合直查表”。直查表会重新引入枚举、隐藏维度
贡献并破坏新人格可组合性。重标定后仍失败则收窄受支持标定点或关闭 L2；不得为过组合 gate 临时手调专属参数。

## 5. `no_change` 与全零分支

数据证明无效与未测全零必须分开：

- `unmeasured/null`：既未完成 screening 也未形成裁决，不得加载；
- `screened_no_candidate/0.0`：预注册网格内没有候选达到工程筛选线，合法 `no_change`，但不声称统计确认无效；
- `confirmed_no_effect/0.0`：确认未过，合法的证据化 `no_change`，该维档只由 L1 提示词调制；
- `confirmed_effective/nonzero`：可进入组合复验；
- mid：设计性 baseline `no_change`，不冒充实验结论。

单格或多个格为 `screened_no_candidate/confirmed_no_effect` 不阻塞 P3-0；数值包按事实保留零值与 provenance。
若 10 个 low/high 格全部落入这两种零值状态，则触发预注册终局：L2 解码调制层裁为
`no_effect_observed_within_preregistered_grid`，P3-A 不为人格功能新增 `GenerationOptions`，P3 继续 L1/L3/L4。
该结果可以形成“L2 不采用”裁决锚，但不能叫非零数值包，也不能外推为所有采样参数均无效。

## 6. 数据归档与可追溯性

每个目标格至少归档：

- screening arm、完整参数、prompt/seed/output 哈希与四项 hard-gate 明细；
- 确认集 40 个 pair id、随机左右、三名评审原始票与多数结果；
- success 数、胜率、精确 p 值、置信区间与 Bonferroni 判定；
- 选择/淘汰理由、最终状态与写入常量表的 exact delta；
- 模型、chat template、依赖版本和所有输入资产 SHA-256。

组合格归档 final applied-options、逐维贡献、8 个配对结果与全部硬 gate。P3-0 最终锚中的每条非零或零 delta
都必须能回溯到唯一目标格和确认记录。

## 7. 执行与验收顺序

1. 本判定线 TA 终裁并与 screening fixture 一起形成**实验预注册锚**；
2. 跑 320 轮 screening，只按 §2 选每格唯一候选；
3. 冻结独立 40-item/维确认集、fresh seeds 与评审包，最多跑 600 轮；
4. 按 `29/40` 冻结每格 `confirmed_effective/confirmed_no_effect`；
5. 跑 80 轮五标定点组合复验；
6. 回填数值包、合法区间、支持矩阵与 provenance，形成 P3-0 最终数值/不采用裁决锚；
7. 最终锚完成后才允许 P3-A 改生产推理协议。

验收行：

- [ ] 10 格目标 rubric 与 200 条确认 prompt 在生成前冻结；
- [ ] screening 与 confirmation 的 prompt/seed/output 零复用；
- [ ] 320 轮 screening 原始证据完整；
- [ ] 最多 600 轮 confirmation 按十格 family 与 `29/40` 判定；
- [ ] 80 轮只覆盖五个 validated anchors；
- [ ] 每条 delta 或 `no_change` 可追溯；
- [ ] 全零终局与组合失败处置按预注册分支执行。
