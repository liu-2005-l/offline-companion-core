# Sprint 4 实施计划（评审冻结版）

> **状态**：已完成（2026-05）  
> **定位**：把 Sprint 0～3 成果「做硬」— 文档入口、跨平台 CI、推理交付说明、记忆草稿工作流  
> **权威原则**：[`architecture_v1.0.md`](./architecture_v1.0.md)  
> **项目地图**：[`PROJECT_STATUS.md`](./PROJECT_STATUS.md)  
> **前置**：Sprint 3 已在 AutoDL `full_acceptance.py` 全绿

---

## 一、目标与非目标

### 目标

| 编号 | 内容 | 状态 |
|------|------|------|
| 4.0 | **`PROJECT_STATUS.md`** + README 入口 + 路线图缺口表同步 | **已完成** |
| 4.1 | CUDA 安装与**性能基线**文档（`docs/inference-cuda.md`） | **已完成** |
| 4.2 | 记忆摘要 **草稿 → 确认**（`on_summarize_request`，**规则优先**，默认关） | **已完成** |
| 4.3 | 知识插件运维化（`sources.yaml`、README；**不进** `run_turn` 主路径） | **已完成** |
| 4.4 | 可执行评测 **≥50** 条（`executable` / `note` 分类统计） | **已完成** |
| 4.5 | **Windows 门禁**：GHA `full_acceptance --skip-gpu` + 现有 pytest 矩阵 | **已完成**（`acceptance_logic.yml`） |

### 非目标（本 Sprint 不做）

- 知识块默认注入普通 `chat`（**D1：默认不进主路径**）
- 向量检索实现（**D3**：仅 schema 预留 + 文档，Sprint 5）
- 联网知识检索、LangChain/Chroma/faiss
- PyInstaller、公网 WebUI（Phase 3）
- 语音 ASR/TTS

---

## 二、冻结决策

| 编号 | 结论 |
|------|------|
| **D1** | 知识 **默认不进** `run_turn`；仅 `/search-knowledge` 显式命令 |
| **D2** | `on_summarize`：**规则/模板生成摘要 → 草稿区 → 用户确认** 后才写入 `memory_chunks` |
| **D3** | 向量 **后置** Sprint 5；Sprint 4 不实现向量检索 |
| **D4** | GPU 单轮耗时超阈值：**WARN 不 FAIL**（避免 CPU 环境误杀） |
| **D5** | 评测 50+ 以 **pytest 可执行** 条目计；`note` 另计 |

---

## 三、实施顺序

```text
4.0 PROJECT_STATUS.md + README + 路线图同步
  ↓
4.5 Windows / Linux 逻辑验收 CI（full_acceptance --skip-gpu）
  ↓
4.1 inference-cuda.md（CUDA 指引 + 性能基线）
  ↓
4.2 记忆草稿区 + on_summarize（规则优先，默认关）
  ↓
4.3 knowledge sources.yaml + README 运维说明
  ↓
4.4 可执行 fixture ≥50
```

---

## 四、4.2 记忆草稿（设计摘要）

### 4.2.1 行为

```text
触发（/summarize 或 on_summarize_request.enabled）
  → 规则/模板从 recent_messages 生成摘要文本（本 Sprint 不调 C1）
  → 写入 memory_drafts（草稿表）
  → CLI：/memory drafts | /memory confirm <id> | /memory discard <id>
  → confirm → MemoryLifecycleManager.add_memory_chunk（显式保存路径）
```

**禁止**：草稿自动进入正式记忆；禁止未确认写入。

### 4.2.2 模块落点

| 层 | 路径 |
|----|------|
| B2 | `core/memory_lifecycle/drafts.py`（或 manager 扩展） |
| C2 | `runtime/storage_index/` 迁移：`memory_drafts` 表 |
| A1 | `cli.py` 子命令；`conversation_orchestrator` 不自动触发（默认关） |

---

## 五、4.5 Windows 门禁

- 已有：`unit_tests.yml`、`static_checks.yml` 双矩阵 `windows-latest`。
- 新增：`acceptance_logic.yml` — `python scripts/full_acceptance.py --skip-gpu`（无 GGUF 的纯逻辑路径）。
- 发布前人工：Windows 本地再跑一遍同上命令（记入 `PROJECT_STATUS.md`）。

---

## 六、4.1 性能基线（文档级）

| 项 | 说明 |
|----|------|
| 目标环境 | Qwen2.5-1.5B Q4_K_M，`n_ctx=2048`，CUDA 版 llama-cpp |
| 期望 | 单轮 **&lt;30s**（体验档）；未达标排查 GPU 层是否真加载 |
| 观测 | 可选 `scripts/stress_test.py`（连续 N 轮内存/耗时趋势，Sprint 4 可选脚本） |
| CI | GPU 步骤不纳入 GHA；仅 WARN 阈值在 `gpu_acceptance` 环境变量扩展（后续） |

详见 [`inference-cuda.md`](./inference-cuda.md)。

---

## 七、退出标准

- [x] `docs/PROJECT_STATUS.md` 与 README 入口一致
- [x] `acceptance_logic.yml` 已添加（推送后由 GHA 验证）
- [ ] Windows 本地 `full_acceptance.py --skip-gpu` 记录一次（发布前人工）
- [x] `inference-cuda.md` 可查
- [ ] 4.2～4.4 完成后：可执行 fixture ≥50；草稿-确认有 pytest

---

## 八、维护

- 架构变更先改 `architecture_v1.0.md`，再改 `PROJECT_STATUS.md` 与本文。
- 新功能同步 fixture 与 `full_acceptance`（或子步骤）。
