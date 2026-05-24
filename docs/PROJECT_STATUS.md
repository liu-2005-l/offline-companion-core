# 项目状态总览（PROJECT_STATUS）

> **一句话**：隐私优先的本地陪伴 Agent **核心库** — 人格锁、可解释记忆、可选本地知识库与显式云端增强。  
> **当前版本**：`0.1.0`（`pyproject.toml`）· **当前 Sprint**：**Sprint 6 已冻结**（2026-05）

---

## 核心能力（已实现）

| 能力 | 状态 | 说明 |
|------|------|------|
| 本地对话 B1→C1 | ✅ | GGUF + `llama-cpp-python`；无模型时 Echo |
| 个人记忆 RAG | ✅ | `#remember` 显式写入；`/memory on` 后 recall + 注入 |
| 记忆可解释 | ✅ | `matched_on`、召回块「重要提醒」 |
| B3 安全分级 | ✅ | `configs/safety_replies/` YAML 话术 |
| B4 本地润色 + 硬降级 | ✅ | 云端失败不回传原文 |
| A3 出站 + Consent | ✅ | `connector.py`；`/cloud-reason` Stub/真实 URL |
| 会话编排 | ✅ | `ConversationOrchestrator` |
| 触发器注册表 | ✅ | 默认仅 `on_explicit_save` |
| 记忆摘要草稿 | ✅ | `/summarize` → 草稿；`/memory confirm` 才写入正式记忆 |
| 导出 / 导入 | ✅ | ZIP bundle + manifest |
| 本地知识 RAG | ✅ | 独立 `knowledge.db`；`/search-knowledge`；默认关 |
| Docker 开发环境 | ✅ | 见 [`docker.md`](./docker.md) |
| 全套验收脚本 | ✅ | `scripts/full_acceptance.py`、`gpu_acceptance.py` |
| 可选记忆向量 | ✅ | `configs/memory/embedding.yaml` **默认关**；哈希袋 + 余弦补强 FTS |
| 长跑观测 | ✅ | `scripts/stress_test.py` |

## 明确非目标（当前不做）

- 静默上云、自动路由上云（主线）
- 联网知识检索
- 向量检索**默认开启**（须显式改 `embedding.yaml`）
- 知识块默认注入普通聊天主路径
- PyInstaller / 公网 WebUI（Phase 3 / **Sprint 6 进行中**）
- LangChain / Chroma / faiss 主路径依赖

## Sprint 5（已完成）

| 子项 | 内容 |
|------|------|
| 5.0 | 文档 — **已完成** |
| 5.1 | 记忆 `embedding_blob` + 召回融合 — **已完成** |
| 5.2 | `scripts/stress_test.py` — **已完成** |
| 5.3 | `gpu_acceptance` 单轮超时 WARN — **已完成** |
| 5.4 | 评测 + `full_acceptance` Sprint5 步骤 — **已完成** |

计划全文：[`sprint-5-plan.md`](./sprint-5-plan.md) · 使用说明：[`memory-embedding.md`](./memory-embedding.md)

## Sprint 6（已冻结，执行中）

| 子项 | 内容 |
|------|------|
| §零 | Sprint 5 收口 — **已完成** |
| 6.0 | 文档 — **已完成** |
| 6.3 | 打包运行时约定 — **已完成**（[`packaging.md`](./packaging.md)） |
| 6.1 | PyInstaller Echo PoC — **已完成**（`scripts/build_portable.py`） |
| 6.2 | 127.0.0.1 Flask WebUI 壳 — **下一步** |
| 6.4 | 打包冒烟 + WebUI 20 轮手动性能基线 |
| 6.5 | executable fixture ≥80（可选） |

计划全文：[`sprint-6-plan.md`](./sprint-6-plan.md) · 打包约定：[`packaging.md`](./packaging.md)

## Sprint 4（已完成）

| 子项 | 内容 |
|------|------|
| 4.0 | 本文 + README 入口 — **已完成** |
| 4.5 | GHA `acceptance_logic.yml` — **已完成** |
| 4.1 | [`inference-cuda.md`](./inference-cuda.md) — **已完成** |
| 4.2 | 记忆摘要 **草稿 → 确认**（`/summarize`，规则优先） — **已完成** |
| 4.3 | [`knowledge-ops.md`](./knowledge-ops.md)、`sources.yaml`、隔离测试 — **已完成** |
| 4.4 | 可执行 fixture **≥50**（`scripts/ci/fixture_stats.py`） — **已完成** |

计划全文：[`sprint-4-plan.md`](./sprint-4-plan.md)

---

## 文档地图

| 想了解… | 打开 |
|---------|------|
| 架构原则（权威） | [`architecture_v1.0.md`](./architecture_v1.0.md) |
| Phase / 缺口 / Sprint 历史 | [`architecture-and-roadmap-v1.0.md`](./architecture-and-roadmap-v1.0.md) |
| 技术栈（Python、GGUF、SQLite） | [`tech-stack-v1.0.md`](./tech-stack-v1.0.md) |
| Sprint 3（已完成） | [`sprint-3-plan.md`](./sprint-3-plan.md) |
| Sprint 4（已完成） | [`sprint-4-plan.md`](./sprint-4-plan.md) |
| Sprint 5（已完成） | [`sprint-5-plan.md`](./sprint-5-plan.md) · [`memory-embedding.md`](./memory-embedding.md) |
| Sprint 6（执行中） | [`sprint-6-plan.md`](./sprint-6-plan.md) · [`packaging.md`](./packaging.md) |
| Docker 冷启动 | [`docker.md`](./docker.md) |
| CUDA / 性能基线 | [`inference-cuda.md`](./inference-cuda.md) |
| 产品方向（历史一页纸） | [`roadmap.md`](./roadmap.md) |

---

## 5 分钟冷启动

### Windows（开发机）

```powershell
git clone <repo-url> offline-companion-core
cd offline-companion-core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,cloud]"
python -m pytest tests/ -q
python scripts/full_acceptance.py --skip-gpu
python -m offline_companion chat --persona configs\personas\default.yaml --privacy local_only
```

REPL 内：`#remember 我喜欢简短回答` → `/memory on` → 继续聊天。

### Linux / AutoDL（含 GPU 全量验收）

```bash
cd ~/offline-companion-core && source .venv/bin/activate
pip install -e ".[dev,inference,cloud]"
export OFFLINE_COMPANION_GGUF=/path/to/model.gguf
export OFFLINE_COMPANION_N_GPU_LAYERS=99
python scripts/full_acceptance.py
```

### 知识库（可选）

```bash
pip install -e ".[dev]"
python scripts/ingest_knowledge.py fixtures/knowledge_sample/sample.jsonl
# configs/knowledge/default.yaml → enabled: true
# CLI: /search-knowledge 压力
```

---

## 验收命令速查

| 场景 | 命令 |
|------|------|
| 日常 PR / 无 GPU | `python scripts/full_acceptance.py --skip-gpu` |
| 跳过知识库步骤 | 加 `--skip-knowledge` |
| 跳过云端 Stub | 加 `--skip-cloud` |
| 服务器全量 | `full_acceptance.py` + `OFFLINE_COMPANION_GGUF` |
| 仅 GPU 子集 | `python scripts/gpu_acceptance.py --root .` |
| 长跑观测 | `python scripts/stress_test.py --turns 50` |
| 跳过压测 | `full_acceptance.py --skip-gpu --skip-stress` |

**发布前建议**：在 **Windows** 与 **Linux** 各执行一次 `full_acceptance.py --skip-gpu` 并记录日期（见 sprint-4-plan §4.5）。

---

## 数据与配置权威源

| 类型 | 路径 |
|------|------|
| 人设 | `configs/personas/` |
| 安全话术 | `configs/safety_replies/` |
| 触发器 | `configs/triggers.yaml` |
| 记忆向量（可选） | `configs/memory/embedding.yaml` |
| 知识插件 | `configs/knowledge/default.yaml` |
| 会话 DB | `{data_root}/companion.db` |
| 知识 DB | `{data_root}/knowledge.db`（独立） |

---

## 维护约定

1. 状态变更时 **先更新本文件**，再改 README 与 sprint 计划。  
2. 架构原则变更只改 `architecture_v1.0.md`，再同步路线图。  
3. 新功能必须带 pytest / fixture / `full_acceptance` 子步骤（如适用）。
