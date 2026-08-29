# v1.8.0 Batch V1 开工方案：真 semantic embedding

状态：v0.1（2026-08-29 开工锚）  
定位：v1.8.0 候选池首战。embedding 是 related 语义关联、R43-R46 tripwire、阈值重校、expansion 决策与 hash-bow 冗余简化的主根。

## 一、前置三问 trace

1. `embed_func` 当前实现：`PersonaSessionCore._assemble_context()` 每轮构造 `EventRecaller(EventRepository(conn), embed_func=lambda text: embed_text(text, dimensions=768))`，来源是 `shared.deterministic_embedding.embed_text()` 的 deterministic hash-bow 768d 向量。
2. `content_embedding` 字段现状：`SemanticEvent.content_embedding` 是 `list[float] | None`，维度固定 `CONTENT_EMBEDDING_DIMENSIONS = 768`；`event.validate()` 只校验维度，不校验归一化；生产写入路径使用 L2 归一化 hash-bow，SQLite 中以 UTF-8 JSON BLOB 存储。T22 降级路径可存 `None`，repo 内无生产 DB 样本，当前无法给出真实 None 占比。
3. sqlite-vec 表 schema：语义事件当前没有 sqlite-vec 虚表；`semantic_events.content_embedding BLOB` 是唯一向量字段，`EventRepository.vector_search()` 读取所有 active 且 embedding 非空事件，在 Python 内计算余弦相似度并按距离排序。repo 内无 `.db/.sqlite` 样本，旧数据量级需迁移 preflight 在用户数据目录运行 `SELECT COUNT(*) FROM semantic_events` 与 `content_embedding IS NULL` 对账。

## 二、Phase A 预注册锚

纪律：R43-R46 必须先钉 degraded，再实现真 embedding；翻转发生时才有归因。

| 用例 | 存档事件 | 查询 | 当前预期 | V1-C 预期 |
| --- | --- | --- | --- | --- |
| R43 | `canine companion naps beside keyboard` | `dog sleeps near laptop` | degraded：零召回 | true embedding 后应翻 correct |
| R44 | `relocate shanghai next spring` | `move magiccity after winter` | degraded：零召回 | true embedding 后应翻 correct |
| R45 | `cilantro causes nausea` | `avoid coriander garnish` | degraded：零召回 | true embedding 后应翻 correct |
| R46 | `offline default privacy policy` | `network access requires consent` | degraded：零召回 | true embedding 后应翻 correct |

四条均显式断言当前 tokenizer 零词面重叠，避免 BM25/hash_bow 词面路径把 degraded 锚误救成 correct。

## 三、related 0.70 预注册

当前只承诺显式 `related_events` 一跳扩展；无显式 ID 链接时，不声明 0.70 语义关联自动注入已经实现。V1-C 需要在真 embedding 与阈值重校后重新判定语义 related 是否翻转。

## 四、阈值重校预注册

真 embedding 空间不得平移 `0.50`。重校方法沿用 Phase 6.2 谷底定位法：

- 复用 `fixtures/semantic_event_similarity_pairs.json`，按 `literal_edit` / `paraphrase` / `dissimilar` 分面计算余弦分布。
- 若三组可分，duplicate / recall 阈值取谷底偏保守侧，并保持写端去重与读端召回同源。
- 若 paraphrase 与 dissimilar 仍严重重叠，不调参装绿，保留 degraded 并记录模型能力边界。
- C2 翻转归因分两步：先只换模型不动阈值，再重校阈值；分别记录模型贡献与阈值贡献。

## 五、选型与降级

推荐 ONNX 中文小模型（bge-small-zh-v1.5 或 gte-small-zh 量级），沿用已有 onnxruntime + tokenizers 栈和 Phase 3 下载链。未下载模型时退回 hash-bow 现行为并输出一次性 warning，不弹窗、不阻断、不静默上云。

## 六、迁移口径

推荐模型就绪后首启动一次性重算全库。迁移脚本按游标三律设计：边界排他、操作后推进游标、非法窗口拒绝；迁移前后对账 active 总数、embedding 非空数与失败数，失败可重试。

## 七、Phase A 验收

- `tests/test_v1_8_semantic_embedding_tripwires.py` 全绿，含 R43-R46 当前 degraded 基线。
- A2 related 语义自动关联 degraded 有测试保护。
- A3 6.5 注入层词面口径注释在档。
- A4 阈值重校方法在本文件预注册，不写死数值。

## 八、Phase B 入口收口口径

- 模型拍板：优先选择 bge-base-zh-v1.5 级 768 维 ONNX embedding，沿用 `CONTENT_EMBEDDING_DIMENSIONS = 768`，避免 padding 与混维解释债。
- 风险修正：旧 hash-bow 768 与新 semantic 768 是同维不同语义空间；混源 cosine 表面合法但分数无意义，因此启动期必须先统一入口、再同步重算全库，完成后才进入服务。
- 单一事实源：`SemanticEmbeddingProvider` 是语义事件 embedding 的唯一生产入口；`PersonaSessionCore` 召回、`EventExtractor` 自动写入、桌面 API 手动写入与 CLI 启动均通过同一 callable。
- 降级口径：provider 按 per-call 判定模型可用性；模型文件缺失或运行中加载失败时退回 deterministic hash-bow 768 维，并只输出一次进程级 warning，不弹窗、不阻断、不静默上云。
- 空间标签：`semantic_events.content_embedding_space` 按行记录 `semantic_onnx_768` / `hash_bow_768` / `none`；召回只比较同空间行，重算只处理目标空间不匹配或 embedding 为空的行，避免 mid-session fallback 把混源垃圾分永久化。
- 性能口径：`EventRepository.vector_search()` 当前保持 Python 线扫，numpy 向量化不混入 V1-B/C，避免污染“模型贡献 vs 阈值贡献”的翻转归因。
