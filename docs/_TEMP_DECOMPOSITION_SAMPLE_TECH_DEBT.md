# 任务拆解样本库技术债

更新时间：2026-08-21

## S1 已完成

- 样本复用 `memory_chunks`，以 `memory_type='decomposition_sample'` 区分本地资产。
- `SampleRepository` 负责 CRUD 与参数化 metadata 更新，`SampleLifecycleManager` 负责用户主权状态机。
- candidate、verified、stale、rejected、archived 状态及对应 append-only 事件已接线。
- 样本步骤只保留七个 few-shot 字段，不保存 `files`。

## S2 已完成

- `SampleRetriever` 仅从 `verified + active` 池执行 BM25、确定性向量和词项重叠三路融合检索。
- few-shot 经过相似度上下限、质量乘法分、异域 MMR、单条 400 token 与总量 1000 token 闸门。
- `shots=None` 与空列表保持原拆解 prompt 字节一致；范例只进入单次 decomposer system prompt。
- 动态设置 `decomp_learning_enabled` 默认开启，只控制检索与注入；关闭期间仍全量留档 candidate，重开后样本积累无空洞。
- LLM 与规则 fallback 拆解均留 candidate，并把来源、注入样本 ID 和候选 ID 写入计划快照。
- 命中样本更新 `injected_count`、`last_hit_at`，同时发布 `sample/injected` 审计事件。

## 后续技术债

1. 设计文档使用 `source_type` 术语，但当前表结构实际字段是 `memory_type`；实现已统一按 `memory_type='decomposition_sample'` 严格过滤，后续文档需同步术语。
2. 样本写入与 DomainEvent append 分属两个提交边界；后续若需要严格事务一致性，应通过 outbox 或重放校验补偿，不能让事件失败回滚已写样本。
3. 当前 `PlanDecomposer` 到 `TaskContext` 的候选绑定沿用编排器单实例的“最近一次拆解”槽位；并发拆解需在后续改为显式 decomposition result DTO，避免跨请求串线。
4. 当前只写入注入次数与最后命中时间；plan 终态结果回写、自动升降级阈值等待 S3。
5. 冷启动成功率使用中性先验 `0.5`，验证系数使用决策表中的 `user=1.0 / auto=0.74`；真实样本量足够后需按 A/B 协议校准。
6. 精确哈希去重、相似合并、软上限和冷归档等待 S5，S2 不提前引入压缩决策。

## S2 Trace 决策归档

- token 预算当前按“中文一字一 token、其他字符四比一”保守估算。该判断绑定 Qwen2.5 BPE；6.1 校准时需用真实 tokenizer 离线测量实际注入量，未来切换模型族必须复核偏差方向。
- candidate 的 `plan_id` 回填失败已隔离；计划未落库形成的悬空 candidate 不进入 verified 检索池，S3 反查不到时 no-op，后续由 S5 的 30 天规则归档，不增加专门清扫。
- 当前工具域签名可能因步骤默认 `skill_id='chat'` 为空，MMR 会退化为 k=1。v2 可在空签名时回退到 `goal_type` 域标签，本轮不提前实现。
- S3 终态回写遇空 provenance 必须直接 no-op，禁止扩大到全量样本。
- edit 会刷新 `modified_at`，检索新鲜度已读取该时间，无需额外字段或迁移。

## S3 已完成

- 计划真正收敛到 DONE 或 FAILED 时，只回写 provenance 命中的样本；空 provenance 直接 no-op。
- BLOCKED 是可恢复暂停，不占用回写幂等标记；恢复后按最终 DONE/FAILED 结果归因。CANCELLED 采用中性 no-op，不增加连续失败。
- 全部步骤 DONE、无 quality retry、无 BLOCKED/DEGRADED/CANCELLED 才算全绿，并将本次 candidate 自动升级为 auto_verified。
- provenance 样本累计 `plan_completed`、`plan_failed` 和 `consecutive_failures`；成功会清零连续失败。
- 至少注入两次后成功率才影响质量分；至少注入三次且连续失败三次，candidate 或 auto_verified 才自动 stale。
- user_verified、rejected、archived 等用户或治理状态只更新统计，不被自动状态迁移覆盖。
- 回写逐样本异常隔离，并在计划快照写入 `_sample_feedback_applied`，普通恢复和重复终态调用不会重复计数。

## S3 后续技术债

- 样本统计与计划快照属于两个提交边界；若进程在样本已更新但计划幂等标记尚未落盘时崩溃，重启后可能重复回写。严格 exactly-once 需 outbox 或按 plan_id 保存反馈收据。

## S4 用户主权入口

- 桌面端提供 7 个纯本地 API，非法状态迁移统一返回 `409 invalid_transition`，状态合法性继续由 B 层生命周期管理器裁决。
- 样本库默认只展示 candidate 与 verified，可按 stale、rejected、archived 等状态筛选；stale 在设置入口显示红点并在页面顶部展示复核摘要。
- 编辑任务描述或步骤会成为 user_verified；确认、丢弃、恢复与编辑均采用前端乐观更新，API 失败时回滚本地视图。
- 终态计划若已有 candidate 提供“查看范例”，否则可幂等“存为范例”；不增加完成弹窗强提醒。

## S5 增长治理

- 注入时同步维护 `last_injected_at`、`similarity_sum` 与 `similarity_count`；缺失 `last_injected_at` 的旧样本不参与 90 天冷归档，避免升级后一刀切。
- exact hash 与大于 0.95 的近重复内容不新增记录，以单条参数化 SQL 原子累加相似度统计；merged 样本 ID 转入本次计划 provenance，终态继续复用 S3 回写链。
- rejected 命中只合并统计，不改变用户状态；user_verified 不参与自动容量淘汰或冷归档。
- verified 池容量治理以“历史相似度均值 × 质量分”升序淘汰，未注入样本代表值为 0；表达式索引暂不增加，单用户量级先使用现有 `memory_type/status` 索引与参数化 JSON 过滤。
- IdleThink 成功收据键为 `maintenance:decomp_samples:<YYYY-MM-DD>`；失败仅记录 warning 且不写收据，同日下一次 idle 自动重试。

### 保留技术债

- 近重复检测当前需扫描本地拆解样本并在进程内计算 token 序列相似度；样本规模显著超过单用户预期后，再评估局部敏感哈希或候选索引，不能提前引入新表破坏零迁移结论。
- L1 的“查重后插入”尚无 JSON 表达式唯一约束；同一进程由 repository 锁串行化，未来若开放多进程并发拆解，需要增加可跨进程仲裁的唯一键或事务收据。
- 现有 `retry_failed_step()` 可重开已失败计划；S3 采用“首次终态归因一次”语义，后续若需要按最终重试结果修正统计，应引入可冲销的 plan outcome，而不是简单清除幂等标记造成双计数。
