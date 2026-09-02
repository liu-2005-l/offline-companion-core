# 人格约束体系 P1 执行规格

版本：v0.1（定义层与承接地基）  
状态：P1 执行中，待预实验与全规格闭合后锚定  
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
- [ ] E/A 拼接微型预实验 fixture、runner、结果与 P2 形态裁决；
- [ ] trait 词表与红线判例（含对抗性）；
- [ ] L4 50 正 50 负 fixture、目标与模式语言规格；
- [ ] 可靠行为判据检测规则；
- [ ] 降档触发规格；
- [ ] 判别协议与判例适用性分析；
- [ ] 维度示例覆盖矩阵规格；
- [ ] P1 锚定 commit。

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
