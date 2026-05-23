# Sprint 6 实施计划（评审冻结版）

> **状态**：已冻结，待执行（2026-05）  
> **定位**：交付形态与本地宿主（Phase 3 起步）— PyInstaller 便携包 PoC + 127.0.0.1 WebUI 壳  
> **前置**：Sprint 5 已完成；**收口项**（§零）全部完成后方可启动 6.1+  
> **入口**：[`PROJECT_STATUS.md`](./PROJECT_STATUS.md)

---

## 零、Sprint 5 收口项（6.x 开发前必完成）

| 项 | 内容 | 状态 |
|----|------|------|
| Z1 | GHA `acceptance_logic.yml` + `full_acceptance.py` UTF-8（`PYTHONIOENCODING` + Windows `reconfigure`） | **已完成** |
| Z2 | `evaluation.yml`（及必要时其它 workflow）同步 `PYTHONIOENCODING=utf-8` | **已完成** |
| Z3 | `stress_test.py` 使用 `tempfile`，不在仓库根目录写 `.stress_companion.db` | **已完成** |
| Z4 | `.gitignore` 明确忽略压测/本地 DB 产物 | **已完成** |

**门禁**：`python scripts/full_acceptance.py --skip-gpu` 全绿后，才进入 §6.1。

---

## 一、目标与非目标

### 目标

| 编号 | 内容 | 状态 |
|------|------|------|
| 6.0 | `sprint-6-plan.md` + `PROJECT_STATUS` / 路线图同步 | **已完成** |
| 6.1 | **PyInstaller 便携包 PoC**（Windows；**仅 EchoBackend**） | 待开始 |
| 6.2 | **127.0.0.1 本地 WebUI 壳**（Flask，A1 宿主） | 待开始 |
| 6.3 | **打包运行时约定**（数据目录、模型路径、日志） | 待开始 |
| 6.4 | **打包冒烟 + WebUI 手动性能基线** | 待开始 |
| 6.5 | **评测扩至 executable ≥80**（可与 6.2 并行） | 待开始（可选） |

### 非目标

- 公网 WebUI（`0.0.0.0`）、Electron / 重型 GUI
- NSIS/WiX 正式安装器（Sprint 7）
- 语音 ASR/TTS
- 联网知识检索、LangChain/Chroma/faiss
- 知识块默认注入普通 `chat` 主路径
- 向量默认开启、云端 embedding
- PoC 阶段捆绑 GGUF / 生产级 GPU 推理打包
- Nuitka 生产化（文档记录为二期备选）

---

## 二、冻结决策

| 编号 | 结论 |
|------|------|
| **P1** | WebUI **只监听 127.0.0.1**；禁止默认绑定局域网 |
| **P2** | 打包产物 **不捆绑 GGUF**；模型路径由用户配置或首次向导指定 |
| **P3** | WebUI 是 **A1 宿主**；HTTP 层 **不得** bypass `ConversationOrchestrator` 直调 B/C |
| **P4** | PyInstaller **PoC 仅验证 EchoBackend 可运行**；`llama-cpp` 动态库打包可行性单独探测，**GPU 模型接入留作后续配置** |
| **P5** | 打包 CI 在 PoC 阶段：**WARN 不 FAIL**；稳定后再升格为门禁 |
| **P6** | WebUI 技术选型：**Flask**（可选 extra `webui`）；比 FastAPI 更轻、便于后续记忆编辑 / 导出向导；**不**进入 B/C 核心依赖 |
| **P7** | WebUI 手动性能基线：连续 **20 轮**浏览器对话，前端无明显卡顿或内存泄漏（6.4 手动验收，非自动化硬门禁） |

---

## 三、实施顺序

```text
§零 收口项（Z2–Z4）
  ↓
6.0 文档冻结
  ↓
6.3 数据目录 / 路径约定（打包前后与 --data-dir 一致）
  ↓
6.1 PyInstaller PoC（Echo 后端；llama 打包可行性探测可选分支）
  ↓
6.2 Flask WebUI 最小壳（127.0.0.1，共用 orchestrator）
  ↓
6.4 打包冒烟 + 20 轮 WebUI 手动基线
  ↓
6.5 评测 executable ≥80（可与 6.2 并行）
```

---

## 四、子项设计摘要

### 6.1 PyInstaller 便携包 PoC

- **完成标准**：
  - PoC 产物 **仅捆绑 EchoBackend**，可启动并完成最小对话（含 `#remember` → `/memory on` → 续聊）。
  - 单独记录 **llama-cpp 动态库** 在 PyInstaller 下的打包探测结果（成功/失败/文档化 workaround）；**不在 PoC 退出标准内要求 GPU 推理可用**。
  - 产出 `scripts/build_portable.py`（或等价）与 `dist/` 构建说明。
- **依赖**：6.3 路径约定先定稿。

### 6.2 127.0.0.1 WebUI（Flask）

- **完成标准**：
  - `python -m offline_companion web --port 8765`（或等价）仅绑定 localhost。
  - 页面可完成与 CLI **等价的最小子集**：发消息、记忆开关、安全话术路径不被绕过。
  - 所有对话经 `ConversationOrchestrator.run_turn`。
- **依赖**：`pip install -e ".[dev,webui]"`（`webui` extra 待 6.2 实现时加入 `pyproject.toml`）。

### 6.3 打包运行时约定

- 数据根：`%LOCALAPPDATA%\OfflineCompanion`（与开发 `--data-dir` 语义一致）。
- 模型：外置路径 / 环境变量；便携包内不包含 GGUF。
- 文档：`docs/packaging.md`（或 `PROJECT_STATUS` 专节）。

### 6.4 打包冒烟与 WebUI 性能基线

- **自动化**：`scripts/packaged_smoke.py` 对 `dist/` 产物做零交互冒烟（Echo）。
- **手动（P7）**：浏览器连续 20 轮对话，观察 DevTools 内存与交互延迟，记录于验收 checklist。
- **CI**：Windows 可选 job；PoC 阶段 WARN（P5）。

### 6.5 评测扩量（可选）

- `fixtures/regression_dialogues.yaml` executable **≥80**。
- `python scripts/ci/fixture_stats.py --min-executable 80` 通过。

---

## 五、退出标准

- [ ] §零 收口项 Z2–Z4 完成
- [ ] Windows 便携包（Echo）完成最小对话流
- [ ] `http://127.0.0.1:<port>` WebUI 完成同等最小对话流
- [ ] 6.4 手动 20 轮 WebUI 无明显卡顿/泄漏（记录日期与浏览器版本）
- [ ] `python scripts/full_acceptance.py --skip-gpu` 仍全绿（开发路径不退化）
- [ ] （若做 6.5）executable fixture ≥ 80

---

## 六、验收命令

```powershell
# 开发路径（仍为准绳）
pip install -e ".[dev,cloud]"
python scripts/full_acceptance.py --skip-gpu

# Sprint 6 新增（实现后）
python scripts/build_portable.py
python scripts/packaged_smoke.py
pip install -e ".[dev,webui]"
python -m offline_companion web --port 8765

# 评测扩量（6.5）
python scripts/ci/fixture_stats.py --min-executable 80
```

---

## 七、维护

- 架构变更先改 `architecture_v1.0.md`，再改 `PROJECT_STATUS.md` 与本文。
- Flask 仅 A1；禁止在 B/C 层 import Flask 或监听非 localhost。
