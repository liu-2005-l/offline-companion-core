# 知识库运维（本地 RAG）

> **隔离原则**：`knowledge.db` 与 `companion.db` / `memory_chunks` **物理分离**；`/search-knowledge` 命中**默认不写入**个人记忆，除非用户另行 `#remember`。

---

## 1. 启用插件

编辑 [`configs/knowledge/default.yaml`](../configs/knowledge/default.yaml)：

```yaml
enabled: true
```

主聊天路径在 `enabled: false` 时**不变**；检索仅通过 `/search-knowledge <query>`。

---

## 2. 导入语料

```bash
python scripts/ingest_knowledge.py fixtures/knowledge_sample/sample.jsonl
```

语料清单与 license 说明：[`configs/knowledge/sources.yaml`](../configs/knowledge/sources.yaml)。

生产环境建议将自备 JSONL 放在数据卷（如 Docker `/data/knowledge/`），勿将大语料提交 git。

---

## 3. CLI 体验闭环

```text
/search-knowledge 压力
```

流程：**B3 安全** → 本地检索（FTS + 中文子串回退）→ 打印片段与 **来源:** URI。

可选：`answer_after_search: true` 时再走 B1→C1→B4（默认 **false**，保证可核对）。

---

## 4. 与记忆的关系

| 数据 | 存储 | 写入方式 |
|------|------|----------|
| 知识片段 | `knowledge.db` | `ingest_knowledge.py` |
| 个人记忆 | `companion.db` → `memory_chunks` | `#remember`、草稿确认等 |

**禁止**：检索结果自动进入 `memory_chunks`。

---

## 相关文档

- [`PROJECT_STATUS.md`](./PROJECT_STATUS.md)
- [`sprint-3-plan.md`](./sprint-3-plan.md)
- [`docker.md`](./docker.md)
