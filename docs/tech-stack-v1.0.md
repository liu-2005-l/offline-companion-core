# Offline Companion · 技术栈 v1.0（已敲定）

> **版本**：v1.0  
> **状态**：已批准，与 [`architecture_v1.0.md`](./architecture_v1.0.md) 及 [`architecture-and-roadmap-v1.0.md`](./architecture-and-roadmap-v1.0.md) 一致  
> **版本真源（规划）**：Docker 镜像内锁定 Python 与依赖版本；本地开发以 `pyproject.toml` + 可选 lock 文件对齐

---

## 一、语言与运行时

| 项目 | 选择 | 理由 |
|------|------|------|
| 语言 | **Python 3.11** | 生态成熟；`llama-cpp-python` 支持稳定；3.12/3.13 部分 wheel 仍有兼容风险 |
| 类型检查 | **mypy（strict，目标）** | 与 CI 集成后强制类型安全；落地进度见路线图 |
| 容器运行时 | **Docker（Phase 2+）** | 镜像内规定**所有**运行时与依赖版本号；模型与语料通过 volume 挂载，**不入 git** |

**约定**：仓库官方支持 **Python 3.11**；CI 主矩阵固定 3.11。个人环境若使用 3.12，须自行验证 `pip install '.[inference]'` 与全量测试。

---

## 二、推理与模型

| 项目 | 选择 | 理由 |
|------|------|------|
| 推理框架 | **llama-cpp-python** | 进程内绑定 GGUF；无需常驻 HTTP 推理服务；支持 CPU / CUDA / Vulkan |
| 默认模型 | **Qwen2.5-1.5B-Instruct，Q4_K_M** | 中文能力强；内存 &lt; 2GB 量级；核显/CPU 可接受 |
| 备选模型 | **Llama-3.2-1B / Gemma-2-2B**（同量化档） | A/B 替换，不并行维护多套默认 |
| 模型文件 | **`.gguf` 本地路径** | **不纳入 git**；本地无文件时由 `scripts/setup_model.sh`（及 Docker entrypoint）**下载** |

**默认模型获取**：优先 **ModelScope**（国内网络）；可通过环境变量改用 Hugging Face。下载目标目录示例：`%LOCALAPPDATA%\OfflineCompanion\models\` 或容器 volume `/data/models`。

---

## 三、数据与存储

| 项目 | 选择 | 理由 |
|------|------|------|
| 主存储 | **SQLite**（标准库 `sqlite3`） | 零额外服务、事务、FTS5 内置、核显零成本 |
| 数据访问 | **原生 sqlite3 + C2 薄封装** | 避免 SQLAlchemy 等重依赖；与当前 `storage_index` 一致 |
| 个人记忆检索 | **FTS5 + 时间衰减 + `matched_on`**（Phase 1） | 可解释、可控；不依赖向量库 |
| 向量（Phase 2+） | **`embedding` BLOB 占位**，暂不引入向量库 | 核显上稠密检索成本高；后续可用 numpy 轻量余弦 |

---

## 四、配置与资源

| 项目 | 选择 | 理由 |
|------|------|------|
| 人设 / 话术 / 触发器 | **YAML（PyYAML）** | 可读、可版本管理；权威目录 **`configs/`** |
| 人设路径 | `configs/personas/` | 根目录 `personas/` 已弃用 |
| 安全话术 | `configs/safety_replies/` | Phase 1 起由 B3 加载，替代代码常量 |
| 触发器默认 | `configs/triggers.yaml` | 默认仅 `on_explicit_save` 开启 |

---

## 五、测试与 CI

| 项目 | 选择 | 理由 |
|------|------|------|
| 测试框架 | **pytest** | 标准、易 mock；已集成 |
| CI | **GitHub Actions** | `ubuntu-latest` + **`windows-latest`** 双矩阵 |
| 评测 | **自定义 harness + pytest** | 对话 JSON/fixture → 断言；目标 50–100 条（Phase 1 后扩） |
| Lint / 格式 | **ruff**（含 format） | 快速；已集成 |
| 架构门禁 | **`scripts/ci/check_imports.py`** 等 | 网络隔离、分层依赖、禁止残留 `import companion` |

**Docker 与 CI（规划）**：镜像内跑相同 pytest 与静态检查；镜像 tag 与 lock 文件对应发布版本。

---

## 六、打包与分发（Phase 3）

| 项目 | 选择 | 理由 |
|------|------|------|
| Windows 便携包 | **PyInstaller（首选）** | 上手快、与 `llama-cpp` 案例多 |
| 优化备选 | **Nuitka** | 体积/性能更优，配置成本高，二期评估 |
| 安装器 | **NSIS 或 WiX** | 正式安装体验 |
| 容器分发 | **Docker** | 自托管、团队统一环境、锁版本；**不等于**用户对话上云 |

**GUI（Phase 2 末 / Phase 3）**：MVP **CLI**；其后优先 **127.0.0.1 本地 WebUI**（属 A1 宿主，不将 B/C 暴露为公网服务）；原生壳（Tauri / WinUI）为可选路线。

---

## 七、明确不引入的依赖

以下依赖**不得**进入主路径依赖（`pyproject.toml` 核心依赖或 B/C 层 import）：

| 排除项 | 原因 |
|--------|------|
| **transformers / torch** | 过重；与 GGUF + llama.cpp 路线冲突 |
| **langchain / llama-index** | 抽象过重；破坏记忆可控与可审计 |
| **chromadb / faiss** | Phase 1 核显不现实；个人记忆以 FTS 为先 |
| **fastapi / flask（对外服务）** | 本地 Agent 不需暴露端口；C1 进程内调用 |
| **Electron 等重型 GUI** | MVP 用 CLI；WebUI 走轻量方案 |

**例外**：A3 `connector.py` 为唯一允许使用 HTTP 客户端的文件（出站，须 A2 许可 + Consent）。

---

## 八、RAG 能力与技术栈的关系

| 能力 | 阶段 | 技术形态 |
|------|------|----------|
| **个人记忆 RAG** | Phase 1 | SQLite `memory_chunks` + FTS + 衰减；B2 `recall()`；B1 自动注入 prompt；**仅显式写入** |
| **通用知识 RAG** | Phase 2 插件 | 独立索引（SQLite FTS/BM25）；**默认关闭**；带来源；经 B4；联网走 A3 |
| **联网检索** | Phase 2 末 / Phase 3 | 高级可选项；每次独立受审；**默认不入记忆库** |

详见 [`architecture-and-roadmap-v1.0.md`](./architecture-and-roadmap-v1.0.md) 第六节、第七节。

---

## 九、维护约定

1. 技术栈变更须更新**本文档版本号**，并在 [`architecture-and-roadmap-v1.0.md`](./architecture-and-roadmap-v1.0.md) 中注明。  
2. Docker 镜像内的 Python、系统库、`llama-cpp-python`、PyYAML 等版本以 **镜像 Dockerfile + lock** 为权威。  
3. 新增依赖须对照第七节「不引入清单」与 CI `check_imports.py`。
