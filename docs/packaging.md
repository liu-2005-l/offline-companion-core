# 打包运行时约定（Sprint 6.3）

> **状态**：评审冻结（2026-05）  
> **用途**：为 PyInstaller 便携包（6.1）与 Flask WebUI（6.2）提供**无歧义**的路径与配置约定。  
> **原则**：默认本地；便携包**不捆绑 GGUF**；开发模式与打包模式**语义一致**，仅默认根目录不同。

---

## 一、模式对照

| 约定项 | 开发模式 | 打包模式 |
|--------|----------|----------|
| **数据目录** | `--data-dir PATH` 覆盖；省略时用 `default_app_paths()`（`shell/policy_engine/rules.py`） | 固定 `%LOCALAPPDATA%\OfflineCompanion`（Linux：`$XDG_DATA_HOME/OfflineCompanion` 或 `~/.local/share/OfflineCompanion`） |
| **模型路径** | `companion chat --model PATH`；验收脚本可读 `OFFLINE_COMPANION_GGUF` | 同左；**推荐** `{数据根}/models/` 下放置 `.gguf`，通过 `--model` 或环境变量指向 |
| **配置文件** | 默认读仓库 `configs/`（如 `configs/personas/default.yaml`） | **首次启动**从内置 `configs/` **复制**到 `{数据根}/configs/`，后续**只从数据目录加载**（用户可改，升级不覆盖已有文件） |
| **日志** | 控制台 stdout/stderr | `{数据根}/logs/` 下按日或按进程写入文件；PoC 阶段可同时保留控制台 |

**说明**：

- v0.1 **已实现**：数据根解析（`default_app_paths`）、`--data-dir`、`--model`、会话 DB / 导出目录。
- **6.1 实现目标**：内置配置首次复制、`logs/` 目录、便携包入口不传 `--data-dir` 且默认 Echo（无 `--model` 时）。

---

## 二、数据目录布局

打包与生产运行下，`{数据根}`（Windows 示例 `%LOCALAPPDATA%\OfflineCompanion`）推荐结构：

```text
OfflineCompanion/
├── companion.db          # 会话与记忆（C2）
├── knowledge.db          # 可选；知识库开启时
├── configs/              # 6.1 起：首次启动从内置复制；后续用户可编辑
│   ├── personas/
│   ├── safety_replies/
│   ├── triggers.yaml
│   └── …
├── personas/             # 用户导出的 persona 副本（已有 AppPaths 字段）
├── exports/              # `/export` 默认输出目录
├── models/               # 约定目录：用户自行放置 .gguf（不随包分发）
└── logs/                 # 6.1 起：文件日志（如 companion.log）
```

与 `AppPaths`（`shared/types.py`）对齐字段：`root`、`db_path`、`personas_dir`、`exports_dir`。`configs/`、`models/`、`logs/` 为 Sprint 6 扩展约定，6.1 打包脚本与启动器须遵守。

---

## 三、路径解析优先级

### 3.1 数据根

1. 显式 `--data-dir`（**仅开发/测试**；便携包入口不得依赖此参数）
2. 否则 `default_data_root() / "OfflineCompanion"`（Windows → `%LOCALAPPDATA%\OfflineCompanion`）

### 3.2 模型（GGUF）

| 场景 | 解析顺序 |
|------|----------|
| 交互 `chat` | `--model PATH` → 省略则 **EchoBackend** |
| `gpu_acceptance` / `full_acceptance` | `--model` → `OFFLINE_COMPANION_GGUF` → 失败则跳过 GPU 步骤 |
| 打包 PoC（6.1） | **不要求模型**；Echo 即满足退出标准 |
| 用户自备模型（打包后） | 推荐 `{数据根}/models/foo.gguf`，启动参数 `--model "%LOCALAPPDATA%\OfflineCompanion\models\foo.gguf"` |

便携包**不包含** `.gguf`；GPU 层数等仍见 [`inference-cuda.md`](./inference-cuda.md)。

### 3.3 人设与安全配置

| 模式 | persona 默认 |
|------|----------------|
| 开发 | `configs/personas/default.yaml`（相对当前工作目录或仓库根） |
| 打包 | `{数据根}/configs/personas/default.yaml`（首次自内置复制） |

其它 YAML（`safety_replies/`、`triggers.yaml`、`memory/embedding.yaml` 等）同理：**打包后以数据目录为权威源**。

---

## 四、环境变量（与打包相关）

| 变量 | 用途 |
|------|------|
| `OFFLINE_COMPANION_GGUF` | 验收 / 脚本用 GGUF 路径；`chat` 子命令仍以 `--model` 为准 |
| `OFFLINE_COMPANION_N_GPU_LAYERS` | GPU 验收与推理层数 |
| `LOCALAPPDATA` | Windows 数据根解析（勿在便携包内硬编码盘符） |
| `PYTHONIOENCODING=utf-8` | Windows CI / 控制台中文输出（见 `.github/workflows/acceptance_logic.yml`） |

---

## 五、与 Sprint 6 子项的衔接

| 子项 | 本文约定如何被使用 |
|------|------------------|
| **6.1 PyInstaller** | 入口 exe 使用默认数据根；内置 `configs/` 种子；Echo-only PoC |
| **6.2 WebUI** | 与 CLI 共用同一 `AppPaths` 与 orchestrator；绑定 `127.0.0.1` |
| **6.4 冒烟** | 对 `dist/` 产物验证：数据目录创建、Echo 最小对话流 |

---

## 六、验收自检（6.3 完成标准）

- [x] 本文档定义开发/打包对照表与目录布局
- [x] 6.1 `scripts/build_portable.py` + Echo 便携包 PoC（见下文）
- [ ] 6.1 `dist/` 便携包在**无 `--data-dir`** 下可写 `%LOCALAPPDATA%\OfflineCompanion`

### 6.1 构建与冒烟（Echo PoC）

```powershell
pip install -e ".[packaging]"
python scripts/build_portable.py
dist\offline_companion\offline_companion.exe
```

PoC 退出标准：双击/运行 exe → 首次复制 `configs/` → `/memory on` → `#remember …` → 续聊（Echo，无 GGUF）。

`llama-cpp` 动态库打包：**不在 PoC 退出标准内**；构建脚本已 `--exclude-module llama_cpp`，后续单独探测并文档化。

开发路径回归（任意 Sprint 6 改动后须仍通过）：

```powershell
pip install -e ".[dev,cloud]"
python scripts/full_acceptance.py --skip-gpu
```

---

## 七、维护

- 路径行为变更须同步本文、`PROJECT_STATUS.md` 与 [`sprint-6-plan.md`](./sprint-6-plan.md)。
- 架构原则不变：B/C 不监听网络；WebUI 仅 A1 宿主。
