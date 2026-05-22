# 个人记忆可选向量（Sprint 5）

> **默认关闭**；开启后仅在 FTS/关键词召回之后做**本地哈希袋 + 余弦**补强，不调用外部 embedding API。

---

## 1. 配置

[`configs/memory/embedding.yaml`](../configs/memory/embedding.yaml)：

| 字段 | 默认 | 说明 |
|------|------|------|
| `enabled` | `false` | 主路径与 Sprint 4 一致 |
| `dimensions` | `128` | 哈希袋维度 |
| `blend_weight` | `0.25` | 向量分对 `combined_score` 的加成上限 |
| `min_cosine` | `0.15` | 低于此不进入候选 |

开启示例：

```yaml
enabled: true
```

---

## 2. 行为

- **写入**：`add_memory_chunk` / `update_memory_chunk` 后，若 `enabled` 则写入 `memory_chunks.embedding_blob`。
- **召回**：`recall()` 先 FTS + 关键词重叠，再对带向量的近期块做余弦补强。
- **可解释**：`matched_on.match_type` 可为 `embedding` 或 `fts+embedding`；含 `embedding_cosine` 字段。

**禁止**：静默上云算向量；不引入 faiss/Chroma。

---

## 3. Schema

- `companion.db` schema **v3** 增加 `embedding_blob BLOB`（迁移幂等）。
- 与 `knowledge.db` **无关**（知识库仍 FTS/子串）。

---

## 4. 观测与压测

```bash
python scripts/stress_test.py --turns 50
python scripts/stress_test.py --turns 50 --memory-on
```

输出：总耗时、单轮均值/峰值、`tracemalloc` 峰值、消息与记忆条数、DB 体积。

GPU 单轮过慢时（非失败）：

```bash
export OFFLINE_COMPANION_GPU_WARN_SEC=30
python scripts/gpu_acceptance.py --root .
```

---

## 相关文档

- [`PROJECT_STATUS.md`](./PROJECT_STATUS.md)
- [`sprint-5-plan.md`](./sprint-5-plan.md)
- [`inference-cuda.md`](./inference-cuda.md)
