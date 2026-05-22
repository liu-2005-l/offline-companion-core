# Sprint 5 实施计划（评审冻结版）

> **状态**：已完成（2026-05）  
> **定位**：可选向量补强个人记忆召回 + 长跑观测；**不**做 PyInstaller / 公网 WebUI（Phase 3）  
> **前置**：Sprint 4 已完成（`full_acceptance --skip-gpu` 全绿）  
> **入口**：[`PROJECT_STATUS.md`](./PROJECT_STATUS.md)

---

## 一、目标与非目标

### 目标

| 编号 | 内容 | 状态 |
|------|------|------|
| 5.0 | `sprint-5-plan.md` + 路线图 / `PROJECT_STATUS` 同步 | **已完成** |
| 5.1 | **可选向量召回**（`embedding_blob`，纯 Python 哈希向量 + 余弦；**默认关**） | **已完成** |
| 5.2 | **`scripts/stress_test.py`**（连续对话观测耗时/内存趋势） | **已完成** |
| 5.3 | `gpu_acceptance` 单轮超时 **WARN**（`OFFLINE_COMPANION_GPU_WARN_SEC`） | **已完成** |
| 5.4 | 评测：`test_memory_embedding.py` + fixture + `full_acceptance` Sprint5 子步骤 | **已完成** |

### 非目标

- **联网知识检索**
- **LangChain / Chroma / faiss** 主路径
- **PyInstaller / 127.0.0.1 WebUI**（Sprint 6 / Phase 3）
- **云端 embedding API**（禁止静默出站）
- 知识库向量（`knowledge.db` 仍 FTS/子串）

---

## 二、冻结决策

| 编号 | 结论 |
|------|------|
| **E1** | 向量 **默认 `enabled: false`**；开启后仍 **优先 FTS + 可解释 `matched_on`** |
| **E2** | 嵌入算法：**本地确定性哈希袋**（无 torch/transformers）；不引入 faiss |
| **E3** | `blend_weight` 默认 **0.25**，仅补强 FTS/关键词未命中场景 |
| **E4** | Schema v3：`memory_chunks.embedding_blob`；旧库迁移幂等 |
| **E5** | 未开启 embedding 时行为与 Sprint 4 **完全一致** |

---

## 三、实施顺序

```text
5.0 文档
  ↓
5.1 schema v3 + configs/memory/embedding.yaml + embedding.py + recall 融合
  ↓
5.2 stress_test.py
  ↓
5.3 gpu_acceptance WARN
  ↓
5.4 pytest + fixture + full_acceptance 扩展
```

---

## 四、5.1 向量（设计摘要）

- 配置：`configs/memory/embedding.yaml` · 说明：[`memory-embedding.md`](./memory-embedding.md)
- 写入：`add_memory_chunk` 后若 enabled 则写入 `embedding_blob`
- 召回：`recall()` 在 FTS/关键词后，对近期有条目的块做余弦相似度补强
- `matched_on.match_type` 可为 `embedding`

---

## 五、退出标准

- [x] `enabled=false` 时 pytest 与 Sprint 4 行为一致
- [x] `enabled=true` 时有独立测试证明向量可改变排序/命中
- [x] `stress_test.py` 可运行并输出报告
- [x] `full_acceptance.py --skip-gpu` 通过（含 Sprint5 子步骤；可用 `--skip-stress` 跳过压测）

---

## 六、验收命令

```bash
python -m pytest tests/test_memory_embedding.py -q
python scripts/stress_test.py --turns 50
python scripts/full_acceptance.py --skip-gpu
```

---

## 七、维护

- 架构变更先改 `architecture_v1.0.md`，再改 `PROJECT_STATUS.md` 与本文。
