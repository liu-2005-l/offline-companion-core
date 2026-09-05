# P3-0 L2 320 轮 screening 报告

版本：v1.2（arm 内平衡重放完成，待外部抽验协议裁决）  
状态：**平衡重审仍选出同四格 candidate；确认集继续暂停**  
规格：`fixtures/persona_constraints/p3_0_l2_screening_spec.yaml`  
判定线：`docs/persona-constraint-p3-0-l2-calibration-verdict-draft.md`

## 0. 执行摘要

- 有效矩阵：`5 维 × 2 外档 × 8 arms × 2 prompts × 2 seeds = 320`；
- baseline 输出：40；candidate 输出：280；
- 自动 gate 全绿：总计 `253/320`，其中 candidate `219/280`；
- 进入方向盲审：30 个 candidate arms，共 `30×4=120` 个配对 item；
- 禁用语义族命中：`0`；L4 `retry_then_fallback` 命中：`0`；空输出：`0`；
- candidate 复制命中：15；异常 finish：46；不完整终止：44，同一行可同时命中 finish 与终止符 gate；
- TA 在完成件封存并计算 SHA-256 后才打开 key；30 arms 中 5 个过 `3/4`，按固定排序选出 4 格唯一 candidate。
- screening 只产生确认集候选，不宣称任何 delta 生效；冻结效应仍需独立确认集达到 `29/40`。

## 1. 一次无效轮次与修复

首轮 `p3-0-l2-screening-v1` 虽完成 320 轮，但评测 prompt 从 P2 mid 单元抽取，而 low/high 目标微型对话同时
被嵌入 system。多个评测问句与注入 user 问句相同，产生 `130/320` 复制命中，无法区分“同题示例复现”与
采样 delta 影响。

该轮整批判无效，未进入方向审读或候选选择，原始证据隔离到：
`artifacts/persona_constraints/p3_0_l2_screening_invalid_prompt_leak/`。`invalid_reason.json` 固定排除原因；
`raw.jsonl` SHA-256 为
`D2562180D436525113DAFE359AA361B4305328318651CB23EB1BD8CDC7DF5622`。

修订版 `v1.1` 在任何有效数据生成前改用十条预注册 held-out prompts，并把规范化包含与
SequenceMatcher 相似度 `<=0.75` 加入 preflight。修订只修测量污染，不沿用或挑选无效轮输出。

## 2. 自动 gate 全量表

“合格 arms”表示该 arm 的四个输出全部通过禁用/L4/复制/finish/非空/完整终止六项 gate。

| 目标格 | baseline | 合格 candidate arms | 被排除原因 |
| --- | --- | --- | --- |
| O-low | 红：finish 2 | 无 | 七个 arms 均有 1–3 条 finish/完整终止红 |
| O-high | 红：finish 1 | 无 | 七个 arms 均有 1–3 条 finish/完整终止红 |
| C-low | 绿 | `temperature_m010`、`temperature_m005`、`temperature_p005`、`temperature_p010`、`top_p_m005`、`top_p_p005` | `top_p_m010` finish 1 |
| C-high | 绿 | `temperature_m010`、`temperature_p005`、`temperature_p010`、`top_p_m010`、`top_p_m005`、`top_p_p005` | `temperature_m005` finish 1 |
| E-low | 绿 | 七个 arms 全部 | 无 |
| E-high | 红：copy 2 | 无 | 七个 arms 各有 1–2 条复制红 |
| A-low | 绿 | `top_p_m010`、`top_p_m005`、`top_p_p005` | 四个 temperature arms 各有 1–2 条 finish/终止红 |
| A-high | 红：finish 1 | `temperature_p010` | 其余六个 arms 各有 1–3 条 finish/终止红 |
| N-low | 绿 | `temperature_m010`、`temperature_m005`、`temperature_p010`、`top_p_m010` | 其余三格各有复制 1 |
| N-high | 绿 | `temperature_m010`、`temperature_m005`、`top_p_m010` | 其余四格各有复制 1 |

自动 gate 已直接给出三个 `screened_no_candidate` 候选：O-low、O-high、E-high。其余七格必须完成盲审后才能
按固定排序选择唯一 candidate；若某格全部合格 arms 都低于 `3/4`，该格同样进入 `screened_no_candidate`。

三格的完整状态名为 `screened_no_candidate_within_preregistered_grid`：只证明当前网格与 gate 内没有候选，不外推
为维度无效或采样参数普遍无效。若后续翻案，只能先锚扩展探索空间并重新 screening，禁止直接送入确认集。

盲审后仅四格有候选，确认预算机械缩为 160 个 pair item。按 C/A/N 三维共享 baseline 计算，最多生成 280 个输出。
省余预算继续弃用，不回填给边界 arm，也不改变每格 `n=40`。

baseline 红只作为目标格风险诊断，不替 candidate 豁免硬 gate。O 的长度红与 E-high 的近端复制说明，F0b
载体的已知风险在 L2 标定中仍在场；不得把“某 candidate 比红 baseline 好”直接写成 delta 生效。

## 3. TA 审读入口

审读文件：

- `artifacts/persona_constraints/p3_0_l2_screening/blind_review_packet.json`：仅含 120 个 eligible pairs；
- `artifacts/persona_constraints/p3_0_l2_screening/blind_review_packet_all.json`：280 个完整 pair 证据，不建议用于筛选；
- `artifacts/persona_constraints/p3_0_l2_screening/blind_review_key.json`：解盲键，方向审读完成前不要打开；
- `artifacts/persona_constraints/p3_0_l2_screening/raw.jsonl`：320 轮原始输出；
- `artifacts/persona_constraints/p3_0_l2_screening/summary.json`：自动 gate 汇总。

对 `blind_review_packet.json` 每行填写：

- `left`：左侧更符合该行 `target_intent + target_signatures`；
- `right`：右侧更符合；
- `indistinguishable`：不可区分或两侧都不符合；
- 可在 `review_note` 记录语义回避、机械模仿或其他未被自动 gate 覆盖的问题。

完成 120 项后才允许读取解盲键并计算各 arm success。自动 gate 全绿且至少 `3/4` success 的 arms 按判定线固定
排序选每格唯一 candidate；不得因看到参数值改变审读或排序。

盲审细则已在 `fixtures/persona_constraints/p3_0_l2_screening_review_protocol.yaml` 预注册：单名 TA 自闭环审读；
枚举仅允许 `left/right/indistinguishable`；不可判与平局均记 candidate failure 且保留在四项分母中，不剔除 pair；
只有任务相关性/事实边界不劣且更符合 target intent，并至少多命中一项 target signature 的一侧可以获胜。

### 3.1 首次盲审结果（已作废）

盲审完成件：`artifacts/persona_constraints/p3_0_l2_screening/blind_review_completed.json`。120 项完整，选择分布为
`left=30 / right=48 / indistinguishable=42`。完成件 SHA-256 在打开 key 前固定为
`6F0BE039F129EB85DB898630C82B2166E17FCFF87D7F177CADA55B7B55A1712E`。

| 目标格 | eligible arms 成绩 | 固定排序结果 |
| --- | --- | --- |
| C-low | `temperature_m010 1/4`、`temperature_m005 2/4`、`temperature_p005 3/4`、`temperature_p010 4/4`、`top_p_m005 2/4`、`top_p_p005 1/4` | `temperature_p005`；以较小标准化绝对步长优先于 `temperature_p010` |
| C-high | `temperature_m010 1/4`、`temperature_p005 2/4`、`temperature_p010 2/4`、`top_p_m010 2/4`、`top_p_m005 1/4`、`top_p_p005 1/4` | `screened_no_candidate_within_preregistered_grid` |
| E-low | `temperature_m010 0/4`、`temperature_m005 1/4`、`temperature_p005 1/4`、`temperature_p010 1/4`、`top_p_m010 1/4`、`top_p_m005 0/4`、`top_p_p005 0/4` | `screened_no_candidate_within_preregistered_grid` |
| A-low | `top_p_m010 3/4`、`top_p_m005 1/4`、`top_p_p005 0/4` | `top_p_m010` |
| A-high | `temperature_p010 3/4` | `temperature_p010` |
| N-low | `temperature_m010 2/4`、`temperature_m005 1/4`、`temperature_p010 3/4`、`top_p_m010 0/4` | `temperature_p010` |
| N-high | `temperature_m010 1/4`、`temperature_m005 2/4`、`top_p_m010 2/4` | `screened_no_candidate_within_preregistered_grid` |

连同自动 gate 已排除的 `O-low/O-high/E-high`，共有六格状态为
`screened_no_candidate_within_preregistered_grid`。完整机器可核结果与固定随机抽验样本见
`artifacts/persona_constraints/p3_0_l2_screening/blind_review_verdict.json`。

首次 key 全量为 `57:63`，但 arm 内允许 `4:0/0:4`；决定性选择本身为左 `30`、右 `48`。尤其首次入选的
`C_low/temperature_p005` 恰为 candidate 全部在右侧，无法排除位置选择与 `3/4` arm 门线耦合。该完成件与裁决
保留为审计证据，但已由 `blind_review_invalidation.json` 明确禁止进入确认集。

### 3.2 平衡重放结果

生成器已改为每个 arm 四对中 candidate 严格左二右二，并更换 blind ID 命名空间。平衡审包 120 对重新逐项审读，
完成件在打开新版 key 前封存；完成件 SHA-256 为
`B68121C6BAF3DD07FADF09BCEAC2ED4A9296B6FDA532D43480922BF56EA5A23C`。

重放后仍有同五个 arms 过 `3/4`，固定排序后仍选择同四格：`C_low=temperature_p005`、
`A_low=top_p_m010`、`A_high=temperature_p010`、`N_low=temperature_p010`。candidate 在左侧时成功
`22/60`，在右侧时成功 `24/60`；原有位置耦合已被设计上消除，裁决稳定性得到一次同数据重放支持。

外部扩抽验仍未启动：四个入选 arms 在现有 screening 中只有 `4×4=16` 个唯一 pair，恰好 candidate 左右 `8:8`。
若要求 30 个唯一 pair，只能混入未入选 arms、重复旧 pair，或生成新输出；前两者不能验证入选 candidate，后一种
实质上已经进入独立确认数据生成。因此 30 条与“确认集不得启动”不能同时满足，需先裁决抽验口径。

## 4. 证据哈希

| 资产 | SHA-256 |
| --- | --- |
| screening fixture | `92D53FC1FEBFF037BB7CFAF8644AB4686903CC1709207C266F718FC651E66924` |
| screening review protocol | `C9279FEFD2B436825E6BCD74A0AE2B8E9711F4FCBEC1AE77D339D8E9ED180DE5` |
| static preflight | `34C2BE6B2EE07A4FFE0B58CB29892BBB01442BC6F942E0C297A70B8E83D39237` |
| GGUF render probe | `A43715746083EB91382F0F5A27A8DC9FA1D2B1D32EF7651D14E360E2FB74F0BE` |
| 320 轮 raw | `69EF30ADB3A4D84EA7628620F53D5E859A065586ED46E20864BEBB9A1D90BC2A` |
| automatic summary | `E04B8DF98DDD5E7E1F200620D924D11881E21C962E158A163A4C0396802D297B` |
| eligible blind packet | `C236F15AC54AAD0424B7169B552A663349B9D2768F06DA7A1CDA14200EE1C011` |
| blind key | `D8FB19BA49005662DE0B37ACCCCE17BDE998CEA6A9BF1B831E697C4ED039920D` |
| completed blind review | `6F0BE039F129EB85DB898630C82B2166E17FCFF87D7F177CADA55B7B55A1712E` |
| blind review verdict | `9CD9B525FCEB39F733DCA191F16E389C062186C537C48563FA2CC2D806640B83` |
| balanced blind packet | `AD2B506EBD1B06F4329BBDDBC12AFDA6EA2B60FC6526B2CBC397500670922331` |
| balanced blind key | `83A8BF899BA7CF4D08D6D7A150D1430A212ABEDDBD7EC5537E3500578305B00F` |
| balanced completed review | `B68121C6BAF3DD07FADF09BCEAC2ED4A9296B6FDA532D43480922BF56EA5A23C` |
| balanced blind verdict | `DA4827CB8EAF80F209569CFD88CCB92353342A344AE596114620584BA8590130` |
| first-review invalidation | `C86B1729E55999280C39AAA8EE07F225FB6698B144C283294695507D0CF6D1FD` |
| balanced review protocol | `7E802FB8CB0D97798183A8DC505813D78121BD8D4170F028CFFB36854E04460C` |

上述哈希对应审读开始前的冻结输入。填写 `review_choice/review_note` 会合理改变审读包哈希；提交审读结果时必须
另记完成版哈希，不能继续引用本表的空白模板哈希。

## 5. 当前验收状态

- [x] v1 首轮污染证据保全并整批排除；
- [x] v1.1 held-out prompt 泄漏 preflight 全绿；
- [x] 模型、chat template 与四份冻结资产哈希一致；
- [x] 320 轮原始输出、自动 gate 与 280 pair 解盲证据完整；
- [x] 30 eligible arms / 120 pair 审读包生成且零参数身份泄漏；
- [x] 首次 120 项盲审因 arm 内放置偏斜作废并保全证据；
- [x] 每 arm `2:2` 平衡重放，完成件先封存后解盲；
- [x] 平衡重审仍按固定排序产出同四格唯一 candidate；
- [ ] 外部抽验口径在 16 条现有唯一 pair 与新增独立输出之间裁决；
- [ ] 过筛 candidate 进入独立确认集规格冻结。
