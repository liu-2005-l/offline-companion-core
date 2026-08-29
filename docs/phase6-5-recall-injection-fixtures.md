# Phase 6.5 召回注入 Fixture 构造表

状态：交付稿（2026-08-29）

范围：敏感区 U15 / U16 / U18 / T19 的 fixture 构造规格。U 系列编号对应 `docs/oc-refactor-phase6-test.md` 的 6.5 段。

## 一、设计纪律

- 远离决策边界：正例词面重叠宽裕命中，负例宽裕不命中。
- 分词颗粒度验证：词面错开对必须按生产 tokenizer / 召回链路验证，不按字面直觉。
- 控制变量到唯一差异源：boost 用例中情绪匹配必须能解释入选差异。
- 断言不锁全文本、具体分数或具体向量，避免 v1.8.0+ 真 embedding 迁移假红。
- 当前物理载体是 LLM 请求的 `memory_block`；C 后端再把 `memory_block` 拼入最终系统消息。

## 二、Fixture

### F1 词面命中对

- 事件：`E-F1-1`，`用户的猫名叫布丁，三岁，喜欢玩逗猫棒`
- 查询：`布丁最近还玩逗猫棒吗`
- 用途：U15 / U17 / T19 正例。
- 预期：`memory_block` 包含 `【相关语义事件】` 与 `布丁`；召回后 `recall_count` 增加。
- v1.7：不翻转，是词面与语义都应命中的稳定锚。

### F2 词面错开对

- 事件：`E-F2-1`，`狸奴常追羽杆嬉戏，午后卧在窗边晒太阳`
- 查询：`猫咪爱玩哪种玩具`
- 用途：U16 主负例。
- 预期：生产 tokenizer 零重叠，hash-bow cosine 为 `0.0`，`memory_block` 不包含语义事件块。
- v1.7：可能随 R43-R46 翻转；当前用例注释为“词面口径构造”。

### F3 情绪 boost 决定性对

- 事件 A：`E-F3-1`，`用户每周六早上跑步五公里`，`emotional_valence=0.8`，`emotional_arousal=0.7`
- 事件 B：`E-F3-2`，`用户跑步前会做热身运动`，中性情绪。
- 查询：`近期安排怎么样`
- 情绪上下文：`joy`，`valence=0.9`，`arousal=0.7`
- 用途：U18。
- 预期：SessionCore 把情绪上下文传入 `EventRecaller`；测试用相同 query embedding 构造 6 个候选，让 boost 改变 top-K 入选集合。不用叙事文本顺序证明，因为最终叙事按时间重排。
- 边界：召回先按 `HASH_BOW_RECALL_THRESHOLD` 过滤，再做 emotion boost；情绪只重排已过阈候选，不把 `0.45 × 1.3` 捞入注入集。

### F4 干净库

- 空语义事件库 + F1 查询。
- 用途：U16 附带 sanity / U24 空状态。
- 预期：无语义事件注入。

## 三、断言映射

| 用例 | Fixture | 断言 |
| --- | --- | --- |
| U15 | F1 | `memory_block` 含 `【相关语义事件】` 与 `布丁` |
| U16 | F2 / F4 | `memory_block` 不含 `【相关语义事件】` |
| U17 | F1 | 注入后 DB `recall_count` 增加 |
| U18 | F3 | 情绪上下文传入 recaller，boost 影响入选候选 |
| T19 | F1 | e2e 发消息捕获 LLM 请求，`memory_block` 同 U15 |

## 四、v1.7 传导

- F1：不翻转。
- F2：可能随 R43-R46 从 degraded 翻 correct。
- F3：结构不翻转，但真 embedding 接入后需复核排序解释。
- R43-R46 先钉 degraded、再实现 embedding、再判翻转的顺序条件不变。
- `HASH_BOW_RECALL_THRESHOLD` 与 `HASH_BOW_DUPLICATE_THRESHOLD` 刻意同源，代表当前 hash-bow 空间里的“明确字面相似”带宽；v1.8.0+ 真 embedding 重校时二者随 R43-R46 一并复核。
