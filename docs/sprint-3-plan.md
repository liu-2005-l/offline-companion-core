# Sprint 3 实施计划（评审冻结版）

> **状态**：评审已通过（2026-05）  
> **权威原则**：[`architecture_v1.0.md`](./architecture_v1.0.md)  
> **总路线图**：[`architecture-and-roadmap-v1.0.md`](./architecture-and-roadmap-v1.0.md)  
> **技术栈**：[`tech-stack-v1.0.md`](./tech-stack-v1.0.md)  
> **前置**：Sprint 0～2 已在服务器 `scripts/full_acceptance.py` 验收通过。

---

## 一、目标与非目标

### 目标

| 编号 | 内容 |
|------|------|
| 3.0 | 文档与路线图与代码一致（**已完成**） |
| 3.1 | **本地**通用知识 RAG 插件（独立 `knowledge.db`，默认关闭）— **已完成** |
| 3.2 | Docker 可复现环境（模型/语料 volume，非公网服务）— **已完成** |
| 3.4 | 评测 fixture 扩至 50+，验收脚本覆盖知识检索 — **已完成**（`regression_dialogues.yaml` 51 条；`full_acceptance` 含 `--skip-knowledge`） |

### 非目标（本 Sprint 不做）

- **3.3 向量嵌入** → 后续版本（Sprint 4+）
- **联网知识检索**（仅本地 FTS/BM25）
- 外部大语料捆绑进 git（版权）
- PyInstaller / 公网 WebUI（Phase 3）
- LangChain / Chroma / faiss 主路径依赖

---

## 二、冻结决策（评审结论）

| 编号 | 决策 | 结论 |
|------|------|------|
| R1 | 知识库存储 | **独立 `knowledge.db`**，与 `companion.db` / `memory_chunks` 物理隔离 |
| R2 | 搜索后是否调 C1 | **MVP 默认仅列片段**（可核对原文）；`answer_after_search` 配置项为 `true` 时再走 B1→C1 |
| R3 | 向量 3.3 | **砍掉**，不纳入 Sprint 3 |
| R4 | 联网检索 | **不做** |
| R5 | 语料 | 仅 **`fixtures/knowledge_sample/`** + 文档说明用户自备语料 |
| R6 | 本文档 | **保留**；路线图只留摘要与链接 |

### 行为冻结（评审补充）

| 场景 | B3 安全 | B4 润色 |
|------|---------|---------|
| `/search-knowledge` 用户 query | **必须先** `classify_user_text`；危机则固定话术，不检索 | 默认列片段：**不过 B4**，原样展示保证可核对 |
| `answer_after_search=true` 且本地生成回答 | 同上（对生成前的用户意图已检查） | **过 B4** `reformat_cloud_reply` |

---

## 三、实施顺序

```text
3.0 文档同步
  ↓
3.2 Docker（与 3.1 设计并行）
  ↓
3.1 知识 RAG 实现
  ↓
3.4 评测扩量 + full_acceptance 扩展
```

3.2 优先于 3.1 实现完成的好处：服务器 / 本地 / 容器内验收环境一致。

---

## 四、3.1 知识 RAG 插件（设计摘要）

### 4.1 配置

- `configs/knowledge/default.yaml`：`enabled: false`、`top_k`、`max_snippet_chars`、`answer_after_search: false`
- `configs/knowledge/sources.yaml`：语料清单与 license 说明（可选）

### 4.2 模块

```
src/offline_companion/core/knowledge_rag/
  schema.py      # 表 + FTS
  ingest.py      # 导入 JSONL/目录
  search.py      # 检索 + 打分
  format.py      # 带来源的展示块（非 B4）
  audit.py       # knowledge_search_log

runtime/storage_index/knowledge_store.py   # 打开 knowledge.db（C2 薄封装）

scripts/ingest_knowledge.py                # 运维导入（语料不进 git）
```

### 4.3 数据模型（独立库）

| 表 | 用途 |
|----|------|
| `knowledge_documents` | 文档元数据、来源 URI |
| `knowledge_chunks` | 正文块 |
| `knowledge_fts` | FTS5 |
| `knowledge_search_log` | 审计：query、hit_ids、session_id |

**禁止**：检索结果默认写入 `memory_chunks`（用户 `#remember` 除外，仍走 B2 显式闸门）。

### 4.4 CLI / 编排

- 命令：`/search-knowledge <query>`
- 流程：

```text
用户 query
  → B3 classify（阻断则固定话术）
  → knowledge_rag.search（本地 FTS）
  → 打印带来源片段（不过 B4）
  → [若 answer_after_search] B1 assemble_reply + B4 + 落库
```

- 编排落点：`shell/ui_host/`（可调 `knowledge_rag`；**不**在 `policy_engine` import `runtime`）

### 4.5 MVP 语料

- `fixtures/knowledge_sample/*.jsonl`（10～30 条，CI 用）
- 生产语料：Docker volume `/data/knowledge/` + `ingest_knowledge.py`

### 4.6 完成标准

- [ ] `enabled=false` 时 `chat` 主路径不变
- [ ] `/search-knowledge` 输出含可核对来源标识
- [ ] 危机 query 不检索、走 B3 话术
- [ ] `answer_after_search=false` 时不调 C1、不过 B4
- [ ] `check_imports` 通过；`full_acceptance` 含 knowledge 子步骤（可 `--skip-knowledge`）

---

## 五、3.2 Docker

| 交付 | 说明 |
|------|------|
| `Dockerfile` | Python 3.11 + CUDA；`pip install -e ".[dev,inference,cloud]"` |
| `docker-compose.yml` | volumes: `models`、`knowledge`、`data` |
| `.dockerignore` | 排除 `.venv`、`*.gguf` |
| README / `docs/docker.md` | 冷启动验收命令 |

- 默认 **不** 暴露 0.0.0.0 对话端口
- 验收：`docker exec … python scripts/full_acceptance.py --skip-gpu`

---

## 六、3.4 评测扩量

- `fixtures/regression_dialogues.yaml` → 50+ 条（含 `knowledge`、`safety`、`memory_recall`）
- `run_eval.py` 支持 `--category`
- `full_acceptance.py` 增加 knowledge ingest + search 断言（零交互）

---

## 七、Sprint 3 退出命令（冷启动）

```bash
cd ~/offline-companion-core && source .venv/bin/activate && \
export OFFLINE_COMPANION_GGUF=/root/data/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf && \
export OFFLINE_COMPANION_N_GPU_LAYERS=99 && \
python scripts/full_acceptance.py
```

3.1 完成后增加：

```bash
python scripts/ci/run_eval.py --fixtures
```

---

## 八、维护

- 架构变更先改 `architecture_v1.0.md`，再改本文与路线图。
- 新功能须同步 fixture 与 `full_acceptance`（或子脚本）。
