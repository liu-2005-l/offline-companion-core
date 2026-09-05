# 人格约束 P3-0 数值包与机器语义锚规格

版本：v0.2.1（标定判定线联动修订稿，待 L2 标定实验 → 数值冻结锚）  
状态：L3 触发语义已具备冻结条件；L2 schema 与实验协议已预注册，但无人格参数增量数据，**不得锚定为终版**  
上游：`docs/persona-constraint-batch-design-v1_5.md`、`docs/persona-constraint-p1-spec.md`、
`docs/persona-constraint-p3-wiring-spec-draft.md`、P1 锚 `bcb8c1a`、P2 闭合锚 `658fdb3`

## 0. 定位与阻塞边界

P3-0 是 P3-A 接线前的数值与语义冻结批，不写生产运行时代码。它必须产出两类可执行规格：

1. **L2 数值包**：每维每档的解码参数增量、确定性叠加规则、支持矩阵与 applied-options trace；
2. **L3 机器语义**：情绪与审计信号的确定性谓词、优先级、一次性消费和低强度效果边界。

本稿已关闭“参数结构、边界离散化、阈值归属、事件规范名”四类歧义。当前唯一数值阻塞是：P1/P2 没有
人格解码增量数据，P2 的解码值只是实验基线，不能冒充 trait delta。必须先按
`docs/persona-constraint-p3-0-l2-calibration-verdict-draft.md` 完成筛选、独立确认与组合复验，再把实验确认的
delta 或证据化 `no_change` 与夹紧区间回填机器规格，才允许形成 P3-0 冻结锚。

禁止以下假闭合：

- 用未测全零或手工拍值宣称 L2 已接线；数据确认的全零只能形成
  `no_effect_observed_within_preregistered_grid` 不采用裁决；
- 把模型 YAML 中未被后端消费的 `default_params` 当作运行时事实；
- 只注册审计事件名而没有精确生产点；
- 用通用 `task.step_retry` 冒充人格降档所需的质量重试事实；
- 把测试内 `_resolve()` 的通过当作生产谓词已经实现。

## 1. 六条 repo trace 结论

### 1.1 本地与云端参数面

当前生产 `InferenceBackend.generate/generate_stream` 协议只暴露 `max_tokens`。本地直调后端实际只传
`messages/max_tokens/stop`；llama-server 后端只传 `model/messages/max_tokens/stream`，并可选传 `seed/stop`。
两者都没有逐请求人格采样参数入口。

P2 二轮 runner 已证明当前 `llama-cpp-python 0.3.34` 直调可接受：

- `temperature`、`top_p`、`top_k`、`min_p`、`typical_p`；
- `presence_penalty`、`frequency_penalty`、`repeat_penalty`。

该事实只证明上游库能力，不证明生产后端已应用。模型 YAML 虽写有 `temperature=0.7/top_p=0.8`，生产推理路径
不读取这两个 `default_params`，不得把它们当 baseline。

云端连接器是通用 OpenAI-compatible 出站接口，不是 DeepSeek 专用实现。`CloudCompletionRequest` 与 HTTP payload
目前都没有人格采样参数字段，只发送 `model/messages/max_tokens`。因此 repo 当前无法证明云端轨支持或应用人格 L2；
P3-A 接线前，云端支持状态必须是 `unsupported_not_applied`，不能透传未知字段后宣称生效。

### 1.2 档位与边界

P 批标定阶段采用离散阶跃，不做连续插值。连续插值属于后续开放调节批，不能提前改变本批的三档实验单位。

- DB/API/UI 整数：`0..33=low`、`34..66=mid`、`67..100=high`；
- YAML 连续值：`0.0 <= value <= 0.33` 为 low，`0.33 < value < 0.67` 为 mid，
  `0.67 <= value <= 1.0` 为 high；
- 两种边界格式先归一化为 `OceanVector`，再走同一档位派生入口；禁止把 YAML 值先四舍五入成整数制造第二套边界；
- NaN、Infinity、布尔值和越界值明确失败，不夹紧、不猜测。

### 1.3 数值来源

P1 冻结了 OCEAN 档位、映射、L1/L3 语义和检测 gate，没有冻结人格解码参数增量。P2 二轮实际生效的：

```yaml
temperature: 0.2
top_p: 0.95
top_k: 40
min_p: 0.05
typical_p: 1.0
presence_penalty: 0.0
frequency_penalty: 0.0
repeat_penalty: 1.0
```

只作为本次标定 baseline。它们不能直接改名为 L2 数值包，也不能从模型 YAML 的另一套默认值反推增量。

### 1.4 降档实现与阈值归属

生产代码目前没有人格降档实现。唯一可执行解析器是 `tests/test_persona_constraint_downgrade.py` 内的测试局部
`_resolve()`；它证明冻结 YAML 自洽，不证明运行时已接线。

`0.45/0.70` 均作用于最终 `EmotionContext.confidence`，不是 embedding 相似度：

- `EmotionClassifier.confidence_threshold=0.45` 是 ONNX 结果接受线，低于该值会回退规则分类器；
- 规则回退一处命中产生 `0.55`，两处命中产生 `0.70`；
- `EmotionContext` 文档声明 confidence 为 `0..1`，但构造器尚未校验；P3-A 谓词入口必须补确定性校验。

### 1.5 三个审计事件的真实状态

以下规范事件均未加入 `DEFAULT_EVENT_TYPES`，也没有生产者：

- `audit/arithmetic_retry_taken`；
- `audit/arithmetic_warning_appended`；
- `audit/quality_retry_taken`。

现有可映射事实为：

- 算术重试：`ArithmeticAuditResult.retried` 只在重试结束后可见；若要影响本次 retry，必须在“首次审计失败、
  即将调用 retry”处分发直接信号，不能事后从返回值倒推；
- 算术警示：最终 `ArithmeticAuditResult.failures` 非空意味着确定性警示已追加；现有 `AssembleReplyResult` 未暴露
  完整算术 trace；
- 质量重试：`quality_retry_counts` 从 `0` 墚到 `1` 是准确事实；内部 `quality_retry_events` 与手动重试都使用
  泛化的 `step_retry`，而 `EventStreamPlanEventPublisher` 不映射 `task.step_retry`。

保留三个规范名，在 P3-A 增加精确生产点。禁止把泛化 `task.step_retry` 设为别名，因为手动重试与质量 gate
自动重试语义不同，会制造误触发。

## 2. L2 数值包机器规格

### 2.1 表结构裁决

否决“按完整档位组合建表”。五维三档的理论组合为 `3^5=243`，完整签名会随组合增长，新人格也不能免改表，
与 v1.5 “每维每档参数增量 + 人格按维度叠加”的既定结构冲突。

冻结资产使用**每维每档 delta 表**：

```yaml
schema_version: 1
baseline_id: p2_preexperiment2_effective_decode
dimension_order: [O, C, E, A, N]
parameters:
  temperature: {baseline: 0.2, minimum: null, maximum: null}
  top_p: {baseline: 0.95, minimum: null, maximum: null}
deltas:
  O:
    low: {temperature: null, top_p: null}
    mid: {temperature: 0.0, top_p: 0.0}
    high: {temperature: null, top_p: null}
```

`null` 表示尚无数据，不能被 loader 接受；`0.0` 仅允许表达经实验确认的 `no_change`，不能用来填洞。表至少覆盖
五维 × 三档，mid 作为标定中心固定 `no_change`，low/high 由 §3 数据决定。

### 2.2 参与参数与控制项

首轮标定只改变 `temperature` 与 `top_p`。其余参数固定为 P2 baseline：

- `top_k=40`、`min_p=0.05`、`typical_p=1.0`；
- `presence_penalty=0.0`、`frequency_penalty=0.0`；
- `repeat_penalty=1.0`。

`repeat_penalty` 必须固定，避免把 P2 已知短前缀复制与 W3 4-gram 问题混进人格风格标定。只有首轮两轴无法为
某维形成有效 delta 时，才可另锚扩轴实验；不得看完结果后临时放开其他参数。

### 2.3 确定性组合

运行时组合公式预注册为：

1. 按 `O,C,E,A,N` 读取档位；
2. 以冻结 baseline 为起点，逐维加同名参数 delta；
3. 应用冻结表中的最终合法区间；
4. 输出不可变 `GenerationOptions` 与逐维 applied-options trace。

加法虽可交换，trace 顺序仍固定，便于逐项归因。最终合法区间必须由组合验证数据决定，本稿不凭经验填写。
任何缺行、非有限值、越界、未知参数或后端未确认应用都返回 `l2_unsupported`，并按 P3 总契约关闭该次人格约束；
禁止静默丢参数继续宣称 L2 生效。

### 2.4 后端支持矩阵

| 轨道 | 上游能力 | repo 当前生产入口 | P3-0 状态 |
| --- | --- | --- | --- |
| llama-cpp-python 直调 | 八个采样参数已由 P2 runner 实测 | 只传 `max_tokens/stop` | 待 P3-A 扩 `GenerationOptions` 并做 applied trace |
| llama-server | 上游 API 可能支持采样参数 | 当前只传 `max_tokens`，可选 `seed/stop` | 未在本仓实测，不得推定支持 |
| 通用云端连接器 | 端点能力不统一 | DTO/payload 均无人格参数 | `unsupported_not_applied` |

P3-A 必须逐后端做请求捕获测试。只有请求 payload 与后端回执/trace 都能证明参数应用，支持状态才可改为
`supported_applied`。

## 3. L2 小规模标定实验预注册

### 3.1 固定环境

- 模型：`models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`；
- SHA-256：`6A1A2EB6D15622BF3C96857206351BA97E1AF16C30D7A74EE38970E434E9407E`；
- llama-cpp-python：`0.3.34`；chat template 使用 GGUF metadata，哈希沿 P2 冻结值；
- baseline：§1.3 全量显式传入；
- fresh seeds：`8191`、`65537`，不得复用 P1/P2 seeds；
- `repeat_penalty=1.0` 全程固定；原始输出、参数、finish reason、usage 与渲染 prompt 全量落盘。

模型哈希、chat template 哈希或依赖版本不符时实验无效，不得把结果写入常量表。

### 3.2 候选网格与轮次

对每个维度的 low/high 分别做 one-factor-at-a-time 标定，mid 保持 baseline：

- `temperature_delta ∈ {-0.10, -0.05, +0.05, +0.10}`，同时 `top_p_delta=0`；
- `top_p_delta ∈ {-0.10, -0.05, +0.05}`，同时 `temperature_delta=0`；
- baseline 对照为两轴 delta 均为 `0`。

每个“维度 × 外档”使用 2 条冻结 held-out 对比探针 × 2 seeds。总量为
`5 维 × 2 外档 × 8 arms × 2 prompts × 2 seeds = 320` 轮。十条探针在跑批前写入 fixture 并锚定，同维
low/high 使用同一用户输入，禁止各档另写题目。探针不得复用 system 内嵌微型对话中的 user 问句；preflight
必须做规范化包含与近重复检查，防止模型因看到同题示例而直接复制 assistant 答案。

首轮不跑 temperature/top_p 笛卡尔积。若两个单轴都有效，只在组合复验中测试各自胜出的最小 delta 组合，
防止先用大网格把基线拟合穿。

### 3.3 判据顺序

候选先过硬 gate，再看风格方向：

1. 冻结禁用语义族命中 `=0`；
2. L4 硬拦截区命中 `=0`，observe-only 单列记账；
3. 短前缀复制 `=0`，检测器历史正控必须命中；
4. 输出完整性全绿，无空输出、截断句或 finish reason 异常；
5. 通过前四项后，才做与 baseline 的盲化逐对方向审读。

每个候选有 4 个配对输出；至少 `3/4` 被判为更接近目标档且不得出现反向多数，才进入候选排序。这只是 screening
工程线：`4/4` 的单侧二项尾概率仍为 `0.0625`，不得写成统计显著，也不替代独立确认或 P4 发布 gate。

### 3.4 最小有效 delta 选择

- 每个 low/high 目标格按判定线规格的固定排序只选一个 candidate 进入独立确认；
- screening 无候选时记 `no_effect_found`；确认未过时记 `confirmed_no_effect`，回填带 provenance 的 `no_change`；
- 单格证据化 `no_change` 不阻塞 P3-0，不得为追求非零改选 screening 第二名；
- 十个 low/high 目标格全部为 `screened_no_candidate/confirmed_no_effect` 时，L2 裁为
  `no_effect_observed_within_preregistered_grid`，P3-A 不为人格解码新增参数协议；
- 选择结果、淘汰原因和 hard-gate 原始证据必须进入报告。

### 3.5 独立确认

screening 与确认集不得复用 prompt、seed 或输出。每维 40 个独立 prompt，low/high 共用 baseline；十格 family 使用
Bonferroni `0.05/10=0.005`，每格 `n=40` 时至少 `29/40`，精确单侧尾概率
`0.003213288047845708`。最大生成量为 `5 维 × 40 prompts × 3 arms = 600`。完整评分、评审与归档口径以
`docs/persona-constraint-p3-0-l2-calibration-verdict-draft.md` 为准。

### 3.6 五标定点组合复验

单维选择后，按五个冻结标定点组合 delta。每人格使用 4 条 P1 高敏感场景 × 2 seeds，并逐项配 baseline，
共 `5 人格 × 4 场景 × 2 seeds × 2 arms = 80` 轮。现有三个 `unvalidated_custom` 不进入本批。组合必须再次
通过全部硬 gate，每标定点至少 `6/8` 更符合目标人格；该线只作非线性交互 smoke，不宣称统计显著。

参数 applied-options 必须精确等于 baseline 加五维 delta；语言输出不设“半档线性误差”，因为模型响应不是线性
系统。最终夹紧区间取能够完整容纳五标定点已选结果的最小稳定区间；若组合后越界或方向反转，按维做交互诊断与
重标定，禁止靠运行时夹紧或人格专属组合表掩盖冲突。

标定产物：

- `fixtures/persona_constraints/p3_0_l2_calibration_spec.yaml`；
- `artifacts/persona_constraints/p3_0_l2_calibration/` 原始证据；
- `docs/persona-constraint-p3-0-l2-calibration-verdict-draft.md`；
- `docs/persona-constraint-p3-0-l2-calibration-report.md`；
- `configs/persona_constraint_decode_parameters.yaml`，其 SHA-256 写入统一入口 manifest。

## 4. L3 机器语义

### 4.1 输入验证与真值表

生产谓词输入为不可变 `PersonaTurnSignals`。`EmotionContext.confidence` 必须是有限数且位于 `0..1`；非法值返回
`invalid_emotion_signal`，本轮人格约束确定性关闭并进入显式 trace，不得夹紧后继续。

| 审计白名单在场 | emotion | confidence | 结果 |
| --- | --- | --- | --- |
| 是 | 任意 | 任意合法值 | `low_intensity_correction` |
| 否 | sadness/anxiety/anger/disgust | `[0.45, 0.70)` | `low_intensity_comfort` |
| 否 | sadness/anxiety/anger/disgust | `[0.70, 1.00]` | `standard_intensity` |
| 否 | sadness/anxiety/anger/disgust | `[0.00, 0.45)` | `standard_intensity`，且不注入情绪条件样本 |
| 否 | neutral/未知标签 | 任意合法值 | `standard_intensity` |

审计纠错优先于情绪共情。未知审计事件不触发，也不得按字符串前缀放宽匹配。

### 4.2 低强度效果

P3-0 将 `set_style_strength_low` 冻结为两件同时发生，防止 L3 空转：

1. L1 必须切到 P2 对应的 `low_intensity_comfort` 或 `low_intensity_correction` 结构样本；
2. 后置表达层进入 `low` profile：感叹号上限为 `0`，禁止追加情绪 suffix 与 persona tone suffix；不得截断句子、
   删除事实、改写数字/URL/代码、替换能力边界或新增 hedging/承诺。

`standard_intensity` 保持当前确定性路径；保护区——安全固定回复、Consent、算术警示、审计块、任务结果与错误码——
始终绕过 L3 并逐字节透传。低强度转换只允许把 `!`/`！` 替换为句号及抑制尚未追加的装饰，不得做自由文本重写。

验收必须同时证明：低强度 profile 有可见机器效果；数字、URL、代码块、否定词与能力边界槽位不变；缺失低强度
语料时整个人格约束关闭，并与同 seed 无约束路径逐字节一致。

### 4.3 规范事件与生产点

三个事件名保持不变并加入 `DEFAULT_EVENT_TYPES`，但 EventStream 只做同源审计镜像，不是触发唯一事实源：

| 事件 | P3-A 精确生产点 | 当前轮消费 |
| --- | --- | --- |
| `audit/arithmetic_retry_taken` | 首次算术审计失败且即将调用 retry | 直接信号作用于该次 retry |
| `audit/arithmetic_warning_appended` | 无可用 retry 或 retry 后仍失败、确定性警示已追加 | 警示不人格化；下一次模型生成最多消费一次 |
| `audit/quality_retry_taken` | 自动质量 gate 使 `quality_retry_counts` 从 0 增到 1 | 同 trace 的下一次模型生成或最终摘要 |

事件 payload 至少含 `session_id/trace_id/source/consumed_in_turn`。镜像追加失败只记录 `event_mirror_failed`，直接信号
仍须生效。`arithmetic_warning_appended` 的一次性状态写入 assistant message meta，进程重启后可恢复；消费后或中间
已有新 assistant 回复即失效，禁止无限降档。

## 5. 冻结资产解析与哈希

P3-0 的机器规格首次执行 P3 v1.2“完整根 + SHA-256”规则：

- loader 按 override → 完整数据目录根 → bundled 根 → repo 根逐个候选验证；
- 统一入口、L2 参数表、L3 降档表及其引用必须来自同一根；
- 所有 source 使用相对路径，拒绝绝对路径与 `..` 越界；
- schema、全部引用和 SHA-256 全过后才选择该根；
- 旧 portable configs 不完整或哈希不符时整体跳过，禁止与 bundled 文件跨根拼接。

标定报告、模型哈希和常量表哈希均进入 P3-0 锚 commit。哈希只证明字节身份，不代替实验有效性。

## 6. P3-A 接口契约

P3-0 冻结后，P3-A 才可新增共享不可变 `GenerationOptions`。最低字段为：

- baseline 与最终 `temperature/top_p`；
- 固定控制项 `top_k/min_p/typical_p/presence_penalty/frequency_penalty/repeat_penalty`；
- `profile_id`、五维档位签名、逐维 delta trace；
- `support_status` 与 `applied_options`。

默认/关闭路径不得仅“数值相同”，还要保持原调用的参数集合语义：未启用人格约束时不额外发送采样字段，确保
既有路径逐字节与逐参数兼容。人格路径只有在后端明确 `supported_applied` 时才发送冻结参数。

## 7. 验收与锚定顺序

1. 本 v0.2 完成 TA trace 修订，仅作为实验预注册草案；
2. 先锚标定 fixture、模型/模板哈希、候选网格、seeds 与 hard gate；
3. 执行 320 轮 screening、最多 600 轮独立确认和 80 轮五标定点组合复验；
4. 产出报告并回填每维每档 delta/证据化 `no_change`、最终合法区间与后端支持矩阵；
5. 机器测试覆盖边界、叠加、非法值、`no_effect_found`、后端未应用与完整根解析；
6. L3 真值表、优先级、一次性事件消费、保护区逐字节透传和 lint 正控全绿；
7. TA 终裁后形成 P3-0 冻结锚，再允许 P3-A 改生产协议与接线。

当前验收状态：

- [x] 每维每档 delta 结构取代完整组合表；
- [x] DB/YAML 两套边界与离散阶跃口径明确；
- [x] P2 baseline 与人格 delta 分离；
- [x] 情绪阈值归属、边界和非法 confidence 语义明确；
- [x] 三审计事件规范名、真实来源与生产缺口明确；
- [x] 标定实验候选网格、seeds、hard gate 和最小有效值规则预注册；
- [ ] 320 轮单维 screening 完成；
- [ ] 最多 600 轮独立确认按十格 family 的 `29/40` 门线完成；
- [ ] 80 轮五标定点组合复验完成；
- [ ] 数值包或 `no_effect_observed_within_preregistered_grid` 不采用裁决、适用时夹紧区间与支持矩阵回填；
- [ ] P3-0 TA 终裁与冻结锚。
