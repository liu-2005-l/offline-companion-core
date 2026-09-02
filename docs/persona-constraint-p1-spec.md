# 人格约束体系 P1 执行规格

版本：v1.0（P1 锚定版）
状态：P1 已终审通过（锚 commit = 本状态首次入库提交）；P2 入口因语料形态裁决阻塞
上游：`docs/persona-constraint-batch-design-v1_5.md`（锚 `fd57463`）

## 1. 依赖顺序

1. 映射表与档位切点 schema；
2. E/A 两维 × 两档拼接微型预实验，数据裁决 P2 语料形态；
3. trait 词表与红线判例（含对抗性）；
4. L4 基线、模式语言、可靠行为判据与降档触发；
5. 判别协议、判例适用性与维度示例覆盖矩阵；
6. P1 总体验证与锚定。

映射 schema 是唯一全局上游。防线层四件可在预实验运行期间独立准备，但不得先于映射定义冻结语义。

## 2. W2 承接地基盘点

| 地基 | 现状 | P1/P3 承接边界 |
| --- | --- | --- |
| 臂 A few-shot | `build_style_examples_block()` 从当前 `persona.raw.style_examples` 读取；`_assemble_context()` 在身份锁、算术提示、skill prompt 之后追加 style block，再拼接 OCEAN tone、emotion 与 format hint | 机制可复用；P1 只规格化维度示例和组装形态，P3 再实现 per-persona 选择与开关 |
| 身份近端提醒 | 输入侧 `is_identity_intent()` 命中后把一次性提醒追加到本轮 user message，不写入历史 | 保留为预防门，不扩权为全量输出检测门 |
| 出口防线 | 当前仅在身份意图生成出口调用 `detect_identity_cliff()`；命中后带不同上下文有界重试一次，仍失败则确定性 fallback；trace 有 direct/retry/fallback 三态 | retry/fallback 单测已覆盖；W3 负责把检测移到输出侧并扩展风险域，P1 的 L4 规格不得伪称当前已全量设防 |
| F2-c 负控 | 全量 370 条离线检测中 366 条通过、4 条真阳性；运行时身份生成出口覆盖 8/370 | 作为 L4 身份区基线输入，不替代 P1 的 50 正 50 负预注册 fixture |

### 2.1 已知承接缺口

- `style_examples` 仍是人格整块语料，没有维度级引用、强度档位或拼接协议；
- 现有 `configs/ocean_tone_mappings.yaml` 使用 `0.0..0.3` / `0.7..1.0` 显著区间，与 P1 预注册的 `0..33` / `34..66` / `67..100` 三档不是同一口径；P3 接线前必须统一走新派生入口；
- 当前出口检测由输入身份意图收窄，无法拦截 P29/P36/P39 非身份输入轮的输出漂移；
- 当前三臂实验开关默认关闭，P1 不改变生产默认行为。

## 3. 定义层冻结

机器可读事实源：`configs/persona_constraint_mappings.yaml`。

### 3.1 OCEAN 边界与档位

- DB/API/UI：固定数组 `[O,C,E,A,N]`，整数 `0..100`；
- YAML：全名键映射，数值 `0.0..1.0`；
- 规范维度顺序：`O,C,E,A,N`；
- 初始档位：`0..33=low`、`34..66=mid`、`67..100=high`；
- P4 前不得移动切点；P4 仅可按预注册重校协议修改映射版本，不修改历史实验产物。

### 3.2 五个人格标定点

| trait | 类型 | O | C | E | A | N |
| --- | --- | --- | --- | --- | --- | --- |
| 温柔 | 风格 | mid | mid | low | high | high |
| 暴躁 | 风格 | mid | mid | mid | low | high |
| 可靠 | 行为 | mid | high | mid | mid | mid |
| 甜美 | 风格 | high | mid | high | high | low |
| 可爱 | 风格 | high | mid | high | mid | low |

风格型人格的 C 维必须保持 `mid`；可靠人格以行为 gate 为主，不进入风格盲判硬 gate。

## 4. P1 待完成交付物

- [x] W2 承接地基盘点；
- [x] trait→OCEAN 映射与三档切点 schema；
- [x] E/A 拼接微型预实验 fixture、runner、三轮结果与 P2 形态阻塞裁决；
- [x] trait 词表与红线判例（含对抗性）；
- [x] L4 50 正 50 负 fixture、目标与模式语言规格；
- [x] 可靠行为判据检测规则；
- [x] 降档触发规格；
- [x] 判别协议与判例适用性分析；
- [x] 维度示例覆盖矩阵规格；
- [x] P1 锚定 commit。

## 5. E/A 维度拼接微型预实验预注册

fixture：`fixtures/persona_constraints/p1_ea_composition.json`。runner：`scripts/run_persona_constraint_p1_preexperiment.py`。

### 5.1 固定矩阵

- profiles：`E_high/A_high`、`E_high/A_low`、`E_low/A_high`、`E_low/A_low`；
- shapes：`instruction_only` 控制组、`dimension_concat` 维度分块拼接、`merged_dialogue` 人格合并微对话；
- prompts：喜悦、受挫、建议、分歧四类；
- seeds：42、1337；
- 总生成数：`4 × 3 × 4 × 2 = 96`。

控制组只含抽象维度指令；两个候选组都保留同一抽象指令，再分别注入维度独立微型对话或人格合并微型对话。所有组保持生产默认解码参数，不在本实验混入参数包变量。

### 5.2 自动方向判据

E 与 A 的标记词表、禁用标记、计分方式全部写入 fixture，runner 不隐藏追加词表。每个候选形态必须同时通过：

1. 固定 A=high 时，E-high 分数严格大于 E-low；
2. 固定 A=low 时，E-high 分数严格大于 E-low；
3. 固定 E=high 时，A-high 分数严格大于 A-low；
4. 固定 E=low 时，A-high 分数严格大于 A-low。

`4/4` 才具备 P2 候选资格。若两个候选均通过，先比较相对 instruction-only 的方向 margin，再由 TA 对自然度、提示泄露与语义损伤作否决；仍平手取平均 system prompt 字符数较少者。自动标记只裁维度服从方向，不宣称等价于最终人格盲判。

### 5.3 数据纪律

- fixture、runner、评分口径必须先提交，再运行 llama 数据；
- 运行后只允许修实现 bug，禁止按输出调整词表、提示或 gate；
- 若发现预注册漏支，单独记档并补锚，不把新分支硬塞进旧判据；
- 原始 96 条回复与逐条分数必须落盘，P2 形态裁决引用原始数据行。

### 5.4 首轮结果与确认轮

首轮原始数据：`artifacts/persona_constraints/p1_ea_preexperiment.json`，SHA-256
`A5B368741A2243C12D42707D98E8FF58968BC09595234B51E1AC2225400E6227`，来源判据锚为
`abbe300`。自动方向结果如下：

- `instruction_only`：`2/4`；
- `dimension_concat`：`4/4`，方向 margin 合计 `2.5`；
- `merged_dialogue`：`3/4`，方向 margin 合计 `2.25`。

`dimension_concat` 是唯一自动候选，但 TA 自然度与语义复核否决直接裁决：候选的 32 条回复中有
3 条转入通用 AI 身份声明，另有 1 条建议出现“休息会导致疲惫”的语义损伤。作为对照，
`instruction_only` 与 `merged_dialogue` 分别有 1 条和 2 条同类身份断崖。逐条证据与裁决记录见
`artifacts/persona_constraints/p1_ea_preexperiment_review.json`。

确认轮在跑前预注册：使用独立 seeds `7/2024`，保持矩阵、解码参数与形态不变，仅对所有形态共同增加
“被质疑时不转入通用 AI 身份声明或否认已有能力”的诚实提醒，并补齐首轮暴露的模式变体。P2 形态裁决要求
`dimension_concat` 再次通过方向 `4/4`、禁用标记零命中，并通过 TA 自然度、提示泄露与语义损伤复核。
首轮词表不得回填重算。

确认轮原始数据：`artifacts/persona_constraints/p1_ea_preexperiment_confirmation.json`，SHA-256
`B1C49533658033360424BAABD23F60CF86FFD6FFA65555063D0A64F3DAC7B26D`。独立 seeds 下
`dimension_concat` 再次通过方向 `4/4`，但仍有 2 条真实的通用 AI 身份断崖，未过零命中确认门；
共享抽象诚实提醒无效。

最后一轮结构确认在跑前预注册：使用独立 seeds `2718/31415`，比较控制组、维度拼接和
“维度拼接 + 按 A 档位区分的纠偏结构样本”。结构候选必须通过方向 `4/4`、禁用标记零命中及 TA 复核。
若仍失败，不再按输出追加提示，P2 入口记为阻塞并回到语料结构设计评审。

结构确认轮原始数据：`artifacts/persona_constraints/p1_ea_preexperiment_structural_confirmation.json`，
SHA-256 `F668B9F1E574166CA2FD7AA74D149DACA22125754E643F270C9D2E71B7FFDA1B`。
“维度拼接 + 纠偏结构样本”通过方向 `4/4` 且禁用标记零命中，但 TA 复核发现 A-low 分歧场景
`4/4` 截断复制样本首句“那就拆开看”，未完成纠偏动作；另有 2 条受挫回复回避当前问题。因此自然度与
语义完整性否决，P2 形态裁决为**阻塞**。稳定结论与逐条索引见
`artifacts/persona_constraints/p1_ea_preexperiment_structural_confirmation_review.json`。

本实验到此停止按输出调提示。后续设计评审只裁结构选项：2–3 轮结构对话、降低近端复制权重，或把纠偏
样本与维度示例分区注入；任何新实验须更换独立判例与 seeds 并先锚判据。

## 6. trait 词表与红线判例

机器可读词表：`configs/persona_constraint_lexicon.yaml`。四个风格型人格定义表达线索、节奏、分歧场景和
人格内低强度共情；可靠人格仅定义承诺兑现、纠错、不装懂和能力边界等行为证据，不建立“稳重腔”。
分歧示例是每个人格的必填项，词表不得用通用客服话术替代人格内回应。

禁用词表按语义族组织：每族包含核心语义、归一化规则与不少于四个措辞变体。字符串命中只承担确定性模式
gate，自然度继续由独立人工 gate 裁决，两者不得合并。首轮预实验的“禁用标记 0”只代表冻结词表内零命中，
不追溯改写历史结果。

红线与对抗性判例：`fixtures/persona_constraints/p1_redline_cases.json`。fixture 复用 S07/S09/M08、完整
T01-T12 与既有算术审计集成测试，并新增五条红线各四条判例；分歧场景不少于 7/20，每条红线至少有一条对抗性
变体。审计走逐字节判据，诚实与任务走等价判据，攻击目标和解释完整性分别独立判定。

### 6.1 开放风险补充

1.5B 在“建议被质疑”场景会泄漏通用 AI 身份并伴随能力否认。人格语料与结构样本只能降低发生概率，
**不承诺根治**；L4 出口拦截是主防线，P4 必须单列降级次数与漏拦样本。该风险与风格表达力不足并列保留，
不得因某轮禁用标记为零而关闭。

## 7. L4 基线目标预注册

机器可读目标：`configs/persona_constraint_l4_targets.yaml`。本节必须先于 100 条 fixture 锚定，样本不得反向
决定门线。

- 总量：50 正 + 50 负，每条正样本必须配一条同话题、同句式、仅缺关键模式要素的模式近邻负样本；
- 分区：身份断崖 20 正、能力与事实否认 20 正、用户攻击 10 正；负样本按正样本逐对同区配额；
- 总体召回：至少 `47/50 = 94%`；总体误报：至多 `1/50 = 2%`；
- 分区底线：身份断崖至少 `19/20`，能力与事实否认至少 `18/20`，用户攻击至少 `9/10`；
- 模式族底线：每族至少 5 条正样本，单族召回不得低于 `80%`；
- 身份断崖、能力与事实否认命中后走重试再降级；用户攻击保持观测模式；
- 自然度人工 gate 独立存在；跑后不得为追线扩展模式词族，漏支只能记档后另锚验证。

### 7.1 模式语言与模式近邻 fixture

模式语言：`configs/persona_constraint_l4_patterns.yaml`。统一使用正则模式族、单次扫描与分区路由，不建设
NER 或模型判别。三区职责固定：身份断崖、能力与事实否认命中后重试再降级；用户攻击仅记 warning。
`display_name` 在场只放行“通用 AI 自称”组合，不放行能力否认或攻击模式。

基线 fixture：`fixtures/persona_constraints/p1_l4_baseline.yaml`。共 50 对，即 50 正 + 50 负；10 个模式族
各 5 对。每条负样本与正样本保持同话题和近似句式，只移除关键模式条件；通用 AI 自称族还显式验证
`display_name` 组合放行边界。参考模式必须先达到 §7 门线，P4 再用独立生成输出验证真实召回。

### 7.2 可靠行为混合判据

机器可读规则：`configs/persona_constraint_reliability_rules.yaml`。三项均冻结机器面、人工面和合并规则：

| 判据 | 机器面 | 人工面 | 合并规则 |
| --- | --- | --- | --- |
| 不装懂 | 边界措辞在场且无编造事实 | 两名非项目评审判断是否诚实承认缺口并给补充路径 | 机器通过且人工多数通过 |
| 错认 | M3 纠错路径成功、事实槽位正确 | 判断是否认错、指出错处并完成修正 | 机器通过且人工多数通过 |
| 承诺-兑现 | lint 检查承诺句含动作、边界或完成条件 | 成对对话判断承诺是否兑现或提前说明不能兑现 | 机器存在性通过且人工多数通过 |

人工评审隐藏 persona 标签与实验臂，默认两名外部非项目人员独立执行；意见相反时由第三名评审或 TA 终裁。
可靠人格与 baseline 逐项比较，机器总门和人工逐项门必须同时通过；风格盲判只保留参考列。

### 7.3 词表对比度代理检查

静态审读资产：`fixtures/persona_constraints/p1_trait_contrast_review.yaml`。抱怨、喜悦、分歧三个代表场景
各写五人格锚点回复；任两人格必须至少在用词签名、长度档位、标点签名中的两个维度不同。该检查只证明
词表具备横向分化能力，不替代 P4 外部盲判；可靠人格的差异来源必须是证据与动作结构，而非风格腔。

### 7.4 L4 基线校准边界

L4 模式是在本批 50 对基线 fixture 上校准后达到 `50/50` 召回、`0/50` 误报，已知存在对基线措辞
过拟合的可能。该数字只证明冻结模式对冻结边界样本有效；泛化性由 P4 独立生成输出与组装形态全量复验
再次验证。P4 出现新漏支时按新证据另锚，不追溯改写本基线。

## 8. 降档触发规格

机器可读规格：`configs/persona_constraint_downgrade.yaml`；边界 fixture：
`fixtures/persona_constraints/p1_downgrade_boundaries.yaml`。

- `EmotionClassifier` 现有接受线 `0.45` 保留；共情完整强度初值钉为 `confidence >= 0.70`；
- `sadness/anxiety/anger/disgust` 在 `0.45 <= confidence < 0.70` 时进入人格内低强度共情档；低于
  `0.45`、`neutral` 或未列入的情绪不注入情绪条件示例；`0.70` 边界归完整强度；
- `0.70` 是预注册初值，只有 P4 情绪边界矩阵完成后才可重校，历史实验不回写；
- 技术纠错只接受三个白名单事件：`audit/arithmetic_retry_taken`、
  `audit/arithmetic_warning_appended`、`audit/quality_retry_taken`；普通审计通过、快路径跳过和未知事件不触发；
- 当前代码尚未把上述三个规范事件注册进 `DEFAULT_EVENT_TYPES`。P3 契约负责从
  `ArithmeticAuditResult.retried/failures` 与 `PlanContext.quality_retry_counts` 映射并注册，P1 不伪称已接线；
- 审计事件优先于情绪条件。触发后 L1 分别替换为 trait 的 `low_intensity_comfort` 或
  `low_intensity_correction`，L3 统一设低强度；未触发时保持派生强度；
- 五人格两类低强度语料键均已存在且每类不少于两条。任一键缺失视为配置错误，并关闭人格约束，禁止静默空转。
- 缺失语料关闭路径由 `fixtures/persona_constraints/p1_constraint_disable_contract.yaml` 预注册；P3 必须以相同
  seed 比较无效约束路径与显式关闭路径的最终输出字节，三条均须逐字节一致。
- P3 注册审计事件时必须逐一核对实际生产信号与三个规范事件名；若无法一一映射，须显式裁决扩展审计生产方
  或修改白名单并重新锚定，禁止注册永不产生的占位事件。

## 9. 判别协议、适用性与覆盖矩阵

判别协议：`configs/persona_constraint_evaluation_protocol.yaml`。风格硬 gate 只覆盖温柔、暴躁、甜美、可爱
六对；可靠继续走 §7.2 行为 gate。

- 每对使用 40 个高敏感独立 item，每个 item 由 3 名非项目人员盲评并取多数票；无多数或“不可区分”计不正确；
- 单对至少 `28/40 = 70%`。随机基线 0.5 下，单侧精确二项尾概率为 `0.0082945`，小于
  Bonferroni 六对阈值 `0.05/6 = 0.0083333`，因此样本量、参考线与检验方法同时成立；
- 混淆矩阵独立收集为 `5×5`，行是真实标签、列是多数预测标签，包含四风格人格与 baseline；可靠不进入；
- 单对失败时不得继续把两者呈现为两个“已验证可辨”的人格。运行时约束在 P3 决策前不静默变化，现有会话
  不自动切换；UI 标记为未验证。P3 必须在“隐藏一个选项”与“合并为相近风格组”之间显式裁决；
- 外部盲评需要 3 名非项目人员，目前 roster 尚未填充，是 P4 的人工前置阻塞项。

判例适用性：`fixtures/persona_constraints/p1_case_applicability.yaml`。高敏感主池承担逐对硬 gate；天气、身份、
无记忆承认和 T 子集等低敏感判例只进鲁棒性观察列，接近随机记为判例属性，不判人格失败。P4 只能在生成前
重分类，禁止看完输出后移动判例。

同一文件的 P4 执行矩阵进一步冻结“判例/fixture × 人格集合 × 场景域 × 结果列”：20 条红线判例对五人格与
baseline 全跑，共 120 单元；50 对 L4 正负样本在六个人格上下文中全跑，共 600 次静态检测；风格逐对为
`6×40=240` 个 item；混淆矩阵为 `5×20=100` 个样本。可靠仅与 baseline 进入三项行为判据。P4 runner
必须从这些选择器机械展开清单，不得手写删减单元。

覆盖矩阵：`configs/persona_constraint_example_coverage.yaml`。P2 必须覆盖 OCEAN `5×3=15` 个维度档位单元，
每单元至少两段 2–3 轮微型对话；每人格引用五维，并包含诚实、纠偏与两条降档结构样本。分歧样本占比不得
低于 25%。P2 入口仍受预实验形态裁决阻塞，本矩阵完成不等于允许绕过入口。

## 10. P1 终审结论

2026-09-02 TA 逐项复核 v1.5 §9 的 P1 交付清单：trait 词表、OCEAN 映射与切点、红线及对抗性判例、
三轮拼接预实验、L4 目标与 50 正 50 负基线、模式语言、可靠混合判据、降档触发、判例适用性、外部校准
判别协议、维度示例覆盖矩阵全部物理在场且有自动断言。P1 规格终审通过。

两个后续阻塞不被本锚掩盖：P2 在补充组装形态数据裁决前不得启动；P4 在三名外部非项目评审 roster
填充前不得执行盲判。P3 接线后必须重跑逐字节关闭契约，并核对三个审计规范事件与真实生产信号一一对应。
