# offline-companion-core

面向 **隐私优先** 的本地陪伴型 Agent **核心库**（Windows 首平台），在**显式同意**前提下为「可选云端增强」预留路径。本仓库是**引擎层**：**SQLite 会话**、**FTS5 记忆检索**、**YAML 人设与角色锁**、**本地危机固定话术**、**可选本地知识库**，以及 **ZIP 单文件导出/导入**（`manifest.json` + JSONL）。

**从这里开始** → [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)（能力清单、文档地图、5 分钟冷启动、验收命令）

| 文档 | 说明 |
|------|------|
| [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) | **项目总览（推荐入口）** |
| [`docs/architecture_v1.0.md`](docs/architecture_v1.0.md) | 架构宪章（原则权威） |
| [`docs/architecture-and-roadmap-v1.0.md`](docs/architecture-and-roadmap-v1.0.md) | Phase / Sprint 路线图 |
| [`docs/sprint-4-plan.md`](docs/sprint-4-plan.md) | 当前 Sprint 4 计划 |
| [`docs/tech-stack-v1.0.md`](docs/tech-stack-v1.0.md) | 技术栈 v1.0 |
| [`docs/inference-cuda.md`](docs/inference-cuda.md) | CUDA 安装与性能基线 |
| [`docs/docker.md`](docs/docker.md) | Docker 开发环境 |
| [`docs/knowledge-ops.md`](docs/knowledge-ops.md) | 知识库导入与隔离说明 |

---

## 隐私模型（简述）

- **默认本地**：会话与记忆的持久化、检索默认在**本机**完成；Windows 下数据根目录一般为 `%LOCALAPPDATA%\OfflineCompanion`（开发可用 `--data-dir` 覆盖）。
- **禁止静默上云**：核心库不主动发起网络请求；未来若接云端，必须在 UI 中披露并经 `ensure_outbound_allowed(...)` 一类闸门，说明**会上传什么 / 不会上传什么 / 目的 / 范围**（`this_turn` / `this_session` / `global`，全局范围需额外确认）。
- **危机处理可完全本地**：关键词分级与固定边界话术**不必**依赖云端模型。

---

## 隐私模式（宿主应用 / CLI）

| 模式 | 行为说明 |
|------|-----------|
| `local_only` | 出站请求在闸门处直接拒绝。**开源核心推荐默认。** |
| `ask_before_cloud` | 出站前需交互确认（或由宿主注入 UI 回调）。**商业形态推荐默认。** |
| `always_ask` | 与 `ask_before_cloud` 在当前实现中同属「先问再走」；预留更严 per-request UI 钩子。 |
| `auto_route_cloud` | **非默认、强警告。** 需 `risk_ack_auto_route=True` 等显式确认；仍非「静默」，但可由集成方承担省略交互的责任。 |

---

## MVP 验收（v0.1 核心）

- **无独显也能「能聊」**：不传 `--model` 时使用 **Echo 后端**；指定 GGUF 并 `pip install '.[inference]'` 后由 **`llama-cpp-python`** 本地推理。
- **重启仍在**：消息与记忆在 SQLite；再次启动时带上相同 `--session-id` 即可续聊。
- **出站必确认**：在 REPL 中输入 `/cloud-demo` 可演练闸门（无真实 HTTP）。`local_only` 会拦截；`ask_before_cloud` 会提示输入 `YES`。
- **全套零交互验收**（推荐 PR / 发布前）：

```powershell
pip install -e ".[dev,cloud]"
python scripts/full_acceptance.py --skip-gpu
```

有 GPU 与 GGUF 时见 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) 全量命令；CUDA 排障见 [`docs/inference-cuda.md`](docs/inference-cuda.md)。

---

## Windows 与 NVIDIA（体验档）

- 安装 **CUDA 版** `llama-cpp-python` 并将 `--n-gpu-layers` 调到大于 0（详见 [`docs/inference-cuda.md`](docs/inference-cuda.md)）。
- **办公核显 / CPU**：请使用**小体积、强量化**的 GGUF，并适当降低 `--n-ctx` 以换流畅首 token。

---

## 快速开始

```powershell
cd offline-companion-core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install -e ".[inference]"   # 可选：本地 GGUF 推理

python -m offline_companion check-model --model C:\path\model.gguf
python -m offline_companion chat --persona configs\personas\default.yaml --privacy local_only
# 本地 GGUF：companion chat --persona configs\personas\default.yaml --model C:\path\model.gguf --n-gpu-layers 20
```

**REPL 内常用命令**

- 行首 `#remember ...`：在记忆开启时写入记忆片段。
- `/memory on|off|list|del <id>|set <id> <text>`：管理记忆表。
- `/export backup.zip`、`/import backup.zip`：**便携数据包**（ZIP 内默认明文；若需保密请在外层再加加密容器）。
- `/summarize`：规则生成摘要**草稿**；`/memory drafts|confirm|discard` 确认或丢弃（不写正式记忆直至 confirm）。
- `/search-knowledge <query>`：本地知识库检索（须在 `configs/knowledge/default.yaml` 中 `enabled: true`）；导入见 [`docs/knowledge-ops.md`](docs/knowledge-ops.md)。
- `/cloud-reason <text>`：经出站闸门 + 云端 Stub/真实 URL + B4 润色（需 `pip install -e ".[cloud]"`）。

**人设路径说明**：仓库内权威人设位于 **`configs/personas/`**；根目录 `personas/` 已弃用，见其中 `DEPRECATED.md`。

---

## 数据目录

- **数据库**：`%LOCALAPPDATA%\OfflineCompanion\companion.db`（可用 `--data-dir` 改写根路径）。
- **导出目录**：默认同根下 `exports\`。
- **Schema 迁移**：`meta.schema_version` 与 `offline_companion.runtime.storage_index.engine` 中的幂等迁移逻辑。

---

## 加密与密钥（诚实边界）

v0.1 导出包**默认不加密**。宿主应用应自行说明：如何依赖系统全盘加密 / DPAPI / 外层加密容器，以及如何**备份密钥**。数据库层加密可在不破坏 schema 契约的前提下后续叠加。

---

## 测试与回归

```powershell
pytest
python scripts/full_acceptance.py --skip-gpu
```

对话类 fixture：[`fixtures/regression_dialogues.yaml`](fixtures/regression_dialogues.yaml)。CI 在 **Windows + Ubuntu** 上跑 pytest 与 `full_acceptance --skip-gpu`（见 `.github/workflows/`）。

---

## 路线图（高层）

语音（ASR/TTS）、稠密向量记忆（当前为 **FTS5** 词法检索）、带**本地人设润色**的云端连接器、记忆去重与 TTL 的 schema 演进等，见 [`docs/roadmap.md`](docs/roadmap.md)。

---

## 许可证

BSD 2-Clause，见仓库根目录 `LICENSE`。
