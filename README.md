# offline-companion-core

面向 **隐私优先** 的本地陪伴型 Agent **核心库**（Windows 首平台）。

**文档入口** → [`docs/README.md`](docs/README.md)

---

## 文档

| 文档 | 说明 |
|------|------|
| [`docs/README.md`](docs/README.md) | **导航**：中英语言入口 |
| [`docs/ARCHITECTURE_v2.0_zh.md`](docs/ARCHITECTURE_v2.0_zh.md) | 原则、分层、共识、Sprint、技术栈 |
| [`docs/SKILL_DEV_GUIDE_v1.0_zh.md`](docs/SKILL_DEV_GUIDE_v1.0_zh.md) | Skill manifest / policy / Sprint 7 |
| [`docs/PLUGIN_DEV_GUIDE_v1.0_zh.md`](docs/PLUGIN_DEV_GUIDE_v1.0_zh.md) | 桌面 WebView Plugin（动态 UI） |
| [`docs/architecture_v1.0.md`](docs/architecture_v1.0.md) | 历史架构基线（只读） |
| [`docs/USER_MANUAL_v1.0_zh.md`](docs/USER_MANUAL_v1.0_zh.md) | 安装、desktop、记忆、验收 |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | 文档版本变更 |

英文版文件名见 [`docs/README.md`](docs/README.md)。

---

## 隐私模型（简述）

- **默认本地**；禁止静默上云；出站须 Consent。
- 危机话术可完全本地完成（B3 YAML）。

---

## 快速开始

```powershell
pip install -e ".[dev,cloud,desktop,skill]"
python -m pytest tests/ -q
python scripts/full_acceptance.py --skip-gpu
python -m offline_companion desktop --force
```

将 Qwen `.gguf` 放入 `models/`（见 `models/registry.yaml`）。CUDA 与 GPU 验收见 [`docs/USER_MANUAL_v1.0_zh.md`](docs/USER_MANUAL_v1.0_zh.md) §七。

---

## CLI 示例

```powershell
python -m offline_companion chat --persona configs\personas\default.yaml --privacy local_only
python -m offline_companion web --port 8765    # 开发宿主，非产品 UI
```

REPL：`#remember …` → 开启记忆 → 续聊。`/search-knowledge` 为内置知识能力，见 [`docs/ARCHITECTURE_v2.0_zh.md`](docs/ARCHITECTURE_v2.0_zh.md) §五。

---

## 仓库结构（概要）

- `src/offline_companion/shell/` — A 层（UI、策略、出站、skill_manager）
- `src/offline_companion/core/` — B 层（人格、记忆、安全、润色）
- `src/offline_companion/runtime/` — C 层（推理、存储）
- `configs/` — 人设、话术、触发器
- `models/registry.yaml` — 本地 GGUF 登记（权重不入 git）

许可证：BSD-2-Clause
