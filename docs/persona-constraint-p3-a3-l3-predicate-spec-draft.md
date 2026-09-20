# P3-A A3 规格批：L3 触发谓词接线 + lint 归并

版本：v0.2（六条事实回填与 §7 裁决落位终版）
状态：终锚规格，实现尚未开始

v0.1→v0.2 演进：TA 六条事实回填 + 五条必改全采纳。v0.1 错误清单：

1. 插入点映射错（会话级快照 ≠ 逐轮链路）；
2. “缺失=降级审计”混淆了语料缺失与信号缺失；
3. “新造审计事件”越权；
4. 0.45 撞车预警被实测关闭（不同物理量）；
5. “从一次性脚本升常驻”过时（既有分散常驻测试）；
6. 降档语料“待纳管”过时（已在六源链）；
7. W3 边界粒度不足（low profile 是低强度定义的一半）。

v0.1 全文作废，以本版为基线。

## 0. 定位与送达状态

- 实现形态：从零实现 L3 谓词。生产代码无既有实现，唯一前身是测试局部 `_resolve()`（`tests/test_persona_constraint_downgrade.py:20`，P3-0 spec §1.4 冻结事实）；
- 送达状态：v0.1 停在聊天云文档未落库。v0.2 重走送达闭环：TA 落库 → repo 在场确认 → 锚定 commit；
- 引用纪律：P3-0 spec 以当前 repo 展开终版为事实源（`docs/persona-constraint-p3-0-numeric-anchor-spec-draft.md`，§1.4 降档现状 / §4.1 冻结真值表 / §4.2 低强度定义）。

### 范围三件

1. L3 触发谓词机器落地（真值表 + 分数源链 + 非法处理）；
2. lint 归并到共享 API + 两项新增扫描（绝对承诺/机制泄漏）；
3. 债务②白名单注册（三事件进 `DEFAULT_EVENT_TYPES`）。

### 不做（防膨胀）

- low profile（`set_style_strength_low`）归 W3——P3-0 §4.2 低强度定义 = “L1 样本切换 + 后置 low profile”两半，A3 只做前半，闭合口径标“部分接线”（§5）；
- C 臂输出侧检测改造归 W3；L4 retry/fallback 接线归 A4；
- 信号异常不新造 DomainEvent——三事件白名单不含信号异常，缺失/非法先进结构化判定 trace，新事件类型需另开规格；
- 单对失败裁决不重裁（wiring spec v1.3 §7 既有归属）。

## 1. L3 触发谓词规格

### 1.1 分数源裁决（v0.1 撞车预警关闭）

- 分数源：最终 `EmotionContext.confidence`。生产链：每轮入口 `conversation_orchestrator.py:115` → ONNX 接受线与规则回退 `classifier.py:127` → 规则分数 `0.55/0.70/...` `classifier.py:111`；
- 撞车裁决：召回阈值当前 hash-bow `0.50` / semantic `0.58`（`event_recaller.py:21`），与 confidence 不是同一物理量。v0.1 的 0.45 同源撞车不存在，预警关闭，落档备查；
- v1.7 档案里的“0.45 过滤线”指旧 HASH_BOW boost 前过滤，该常数已被后续 semantic 升级重构，与 L3 无涉。

### 1.2 真值表（P3-0 §4.1 冻结语义，A3 实例化）

| 输入形态 | 判定 | 动作 | 审计 |
| --- | --- | --- | --- |
| 无 audit 场景 + 缺失 emotion | 合法常态 | `standard_intensity`（标准路径） | 零事件 |
| neutral / 未知标签 | 合法不触发 | `standard_intensity` | 零事件 |
| `confidence < 0.45` | 合法不触发 | `standard_intensity` | 零事件 |
| `0.45 ≤ x < 0.70` | 触发降档 | 人格内低强度共情样本（逐轮临时块，§2.2） | 结构化 trace |
| `x ≥ 0.70` | 合法标准强度 | P2 冻结映射对应标准语料 | 结构化 trace |
| 非有限（NaN/inf）/ 非数值 / 越界（`x<0` 或 `x>1`） | `invalid_emotion_signal` | 关闭本轮人格约束 | 结构化 trace（非 DomainEvent） |

语义修正：v0.1 把“信号缺失”归入降级 + degraded-for-cause 审计，混淆了两个“缺失”：

- 语料缺失 → 确定性关闭约束（P1 冻结，同 seed 逐字节一致）——资产侧异常；
- 信号缺失 / 中性 / 低分 → `standard_intensity`（合法常态，零审计）。

只有“数值本体不可信”（非有限/非数值/越界）才是 invalid。非法 ≠ 合法的“不触发”；两者输出行为可以一致，但 trace 必须分型。

### 1.3 输入校验边界

- `emotion_context is None` 是合法的信号缺失，走 `standard_intensity`，不产事件；
- 谓词入口显式拒绝 `bool`、非数值、NaN、正负无穷和 `0..1` 之外的值，统一返回 `invalid_emotion_signal`；
- `EmotionContext` 构造层当前不校验 confidence（`context.py:43`），A3 只在谓词入口 fail-closed 校验，不修改构造器；
- 构造层统一加固记为后续债务，不扩入 A3。

### 1.4 优先级（P1 冻结）

- 审计触发 > 情绪触发；
- L1/L3 一一对应（每个触发域只有一个 L1 落点）。

## 2. 逐轮接线

### 2.1 插入点

- v0.1 错误：把 L3 插在 `session_binding` 链 L1 上游。`session_binding` 的 L1 只在会话快照创建时运行（`session_binding.py:687`），属于会话级；
- 正确插入点：情绪分类之后、`PersonaSessionCore._assemble_context()` 生成当轮 prompt 之前（`session.py:446`），属于逐轮链路；
- 数据流“signals → L3 → L1”是逻辑方向，不是施工位置映射。

### 2.2 快照边界

- 会话快照保留 A2 基础 L1（烧入态，不动）；
- L3 选择的低强度样本是逐轮临时块，不回写历史快照；
- 验收钩子：快照回放路径不含任何 L3 注入残留。

### 2.3 audit 触发通路（§7 已裁决）

三事件采用显式信号通路。生产点构造不可变 `PersonaTurnSignals`，直接传给对应生成路径；DomainEvent 只镜像同一事实，不参与触发判定：

1. `audit/arithmetic_retry_taken`：首次 failures 非空、即将调用 retry 时，把信号直接传给 retry 回调；retry 必须用该信号重新组装逐轮 `low_intensity_correction` 临时块，使纠错样本在**同次 retry** 生效，不等待下一轮；
2. `audit/arithmetic_warning_appended`：警示正文属于保护区，不人格化。警示追加事实随组装结果传到消息持久化层，作为一次性标记写入 assistant message meta；下一次模型生成最多消费一次，消费后立即失效，中间已有新 assistant 回复时也失效；
3. `audit/quality_retry_taken`：`quality_retry_counts` 从 `0→1` 后，把信号写入同 trace 的计划上下文，直接传给第二次执行或最终摘要生成，不依赖事件流回读。

冻结约束：

- EventStream 只作同源审计镜像；镜像追加失败只进入 trace，不得吞掉或改变直接信号；
- 显式信号通路允许对结果 DTO、retry 回调协议和计划上下文做最小扩展，但不得把逐轮临时块写回会话快照；
- `task.step_retry` 是泛化事件，不得作为 `audit/quality_retry_taken` 别名；
- 审计信号与情绪信号同时在场时，当前生成尝试按“审计触发 > 情绪触发”解析。

## 3. 债务②白名单注册

### 3.1 三事件与生产点

| 事件名 | 生产点 | 触发条件 |
| --- | --- | --- |
| `audit/arithmetic_retry_taken` | `arithmetic_verifier.py:142` | 首次 failures 非空、调用 retry 前 |
| `audit/arithmetic_warning_appended` | `arithmetic_verifier.py:165/:170` | retry 后仍失败或无 retry、警示完成追加处 |
| `audit/quality_retry_taken` | `plan_orchestrator.py:1097` | 计数 `0→1` 后、第二次执行前 |

冻结名来源：`configs/persona_constraint_downgrade.yaml:15`。

### 3.2 注册动作

- 注册目标：`DEFAULT_EVENT_TYPES`（`event_stream/registry.py:8`），不是 `memory_lifecycle/event_types.py:7`；
- 注册 = 枚举登记 + 三生产点接线产 DomainEvent，两步闭合；
- 注册前 false 的负控保留，防只登记不接线的假注册；
- 注册是静态代码动作，不做运行时动态注册机制。

## 4. lint 归并 + 第七源纳管

### 4.1 归并

禁用族 / L4 / 短前缀复制 / 分歧占比 ≥25% / display_name / schema 与引用完整性 / 六源哈希已有分散常驻测试，v0.1“从一次性脚本升常驻”口径作废。

A3 共享 lint API 纳入禁用语义族、L4 模式族、短前缀复制、分歧占比、display_name、schema 与引用完整性，以及 §4.2 两项新增扫描。测试消费共享 API 而不是复制检查逻辑；不改变既有断言语义，归并后全量测试不变绿是阻断条件。

发布态哈希校验继续由 `assets.py` 独占，不搬入 lint、不复制哈希算法。CI 可以同时调用共享 lint API 与资产加载器，但两者保持职责分离；`downgrade.yaml` 篡改正控及其他发布物篡改正控仍归资产测试。

### 4.2 真正新增两件

- 全语料绝对承诺扫描（N-low 修正教训）；
- 全语料机制泄漏扫描（技术降档修正教训）；
- 两项各带注入式正控：坏语料现场构造，lint 必红。

### 4.3 `downgrade.yaml` 第七源纳管

- 降档语料本体已在六源链：`structural_corpus.yaml:69` 三条结构样本 + `persona_compositions` 五人格引用；
- 真正未入链的是 `downgrade.yaml` 本身，其中包含阈值 `0.45/0.70` 与三事件冻结名；
- 决定：`downgrade.yaml` 纳管第七源，重算发布常量（`assets.py:18`），并延伸 manifest 校验链。

## 5. 闭合口径：部分接线诚实标记

P3-0 §4.2 把低强度定义为“L1 样本切换 + 后置 low profile”同时发生。A3 只完成前者以及触发谓词、三事件注册；low profile 归 W3。

A3 闭合标记必须写明：**部分接线——L1 样本切换与触发谓词闭合，`set_style_strength_low` 待 W3。** 禁止宣告低强度全闭合。

## 6. 验收行（预注册）

1. 真值表 fixture：§1.2 六行逐格断言，覆盖 `0.45/0.70` 双侧、`0/1`、NaN/inf、非数值；
2. 降档方向断言：触发后落到 P2 冻结映射对应降档语料，不落任意位置；
3. `standard_intensity` 零审计：缺失/中性/低分三形态断言零事件；
4. `invalid_emotion_signal`：三形态各一条，结构化 trace 在场 + 本轮约束关闭 + 零 DomainEvent；
5. 快照边界：L3 注入后快照逐字节不变，回放路径无注入残留；
6. 三事件注册与直达信号：三生产点各一条 DomainEvent 镜像判例，并逐通路断言信号到达点——算术 retry 信号使逐轮纠错块在同次 retry 重组装中在场；warning 标记写入 assistant message meta、下一次生成消费一次后失效；quality 信号在同 trace 第二次执行或最终摘要到位；另含镜像追加失败不吞直接信号负控、未注册事件负控及 `task.step_retry` 非别名断言；
7. lint 归并等价：共享 API 归并后既有 lint 全绿 + 两项新增扫描正控必红；
8. 第七源：`downgrade.yaml` 篡改拒绝 + 发布常量重算后七源校验全绿；
9. L3 零侵入：关闭态组装输出与 `53acf4c` 态逐字节一致 + `1389 passed` 基线不倒退；
10. 部分接线标记：闭合报告含 §5 标记原文。

## 7. TA trace 裁决记录

1. audit 通路：否决 EventStream 触发源，采用显式 `PersonaTurnSignals`；算术 retry 同次生效，warning 通过 assistant message meta 一次性消费，quality 信号在同 trace 生效；EventStream 仅作可失败的审计镜像；
2. confidence 校验：只在谓词入口校验，合法 `None` 走标准路径；显式拒绝 `bool`、非数值、非有限值与越界值，构造层加固留债务；
3. lint 归并：内容、语义、schema 与引用规则进入共享 API；发布哈希继续由 `assets.py` 独占，CI 同调但不混责；
4. P3-0 对齐：当前 repo 展开版 §4.1/§4.2/§4.3 与本规格无冲突；A3 仅为部分接线，在 W3 补齐 low profile 前不得宣告或发布完整 `set_style_strength_low` 能力。

## 8. 执行顺序

v0.2 终锚 → 谓词纯函数 + 真值表 fixture → 逐轮接线 + 快照边界 → 三事件注册 → lint 归并 + 第七源 → 零侵入证明 → 验收行逐条核 + 部分接线标记。
