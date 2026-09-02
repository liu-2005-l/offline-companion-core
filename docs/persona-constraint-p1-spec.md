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
