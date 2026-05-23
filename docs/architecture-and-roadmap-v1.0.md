# Offline Companion · 架构宪章与实施路线图

> **版本**：v1.1（记忆 RAG + 技术栈引用）  
> **生效日期**：Phase 0 骨架落地后  
> **架构原则权威正文**：[`architecture_v1.0.md`](./architecture_v1.0.md)  
> **技术栈（已敲定）**：[`tech-stack-v1.0.md`](./tech-stack-v1.0.md)  
> **产品方向清单（历史一页纸）**：[`roadmap.md`](./roadmap.md)

本文档在宪章基础上汇总 **Phase 0 现状、缺口、Phase 1/2 路线与维护纪律**；与 `architecture_v1.0.md` 冲突时以宪章正文为准。

---

## 一、核心原则（不可妥协）

1. **陪伴优先**：交互质量与一致性高于工具能力；人设边界稳定，任何输出必须经过人格锁。
2. **工具为次**：工具链是可选插件，不得污染主路径的信任与延迟。
3. **记忆透明**：用户可看见、编辑、删除、导出所有记忆，并理解「为何被召回」。
4. **隐私第一**：默认本地闭环，网络出站须显式授权；禁止静默上云。
5. **出站可审计**：任何云端请求必须经过策略许可，生成 Consent Artifact（最小上传、目的、范围、二次确认）。
6. **硬项同权**：危机分级/固定话术、评测回归集、数据导出/迁移/密钥说明与功能同权重。

---

## 二、系统分层（三层七域，九模块）

| 层 | 包路径 | 网络权限 | 包含模块 |
|----|--------|----------|----------|
| A · 策略壳 | `offline_companion.shell` | 仅 A3，且须 A2 许可 | A1 UI 宿主、A2 策略引擎、A3 出站管理器 |
| B · 陪伴核 | `offline_companion.core` | **禁止** | B1 人格与会话、B2 记忆生命周期、B3 安全边界分级、B4 本地润色器 |
| C · 算力与 IO | `offline_companion.runtime` | **禁止** | C1 本地推理后端、C2 存储与索引引擎 |
| 横切 | `offline_companion.shared` | — | DTO / 异常；**禁止** import A/B/C |

### 依赖方向（单向，不可逆）

- `A1 → A2`
- `A2 → B`（编排与受控访问 B 层；**A2 不得直接 import `runtime`**）
- `A2 → A3`（出站前策略许可）
- `B → C`（如 B2 → C2；B4 → C1）
- **禁止**：`B → A`、`C → A`、`C → B`
- **B / C 禁止**网络库 import；白名单：`shell/outbound_manager/connector.py`

### 单轮对话推荐顺序（Phase 1 目标）

```text
用户输入 → B3 安全分级（阻断则固定话术返回）
         → B2 recall（仅当记忆开关 on；只读已显式保存的记忆）
         → B1 assemble_reply（人设 + history + 记忆块「你可能想起来的」）
         → C1 generate
         → （可选）B4 润色
         → 落库 assistant 消息
```

---

## 三、关键设计锚点

- **个人记忆 RAG（Phase 1）**：每轮 **主动 recall** + B1 **自动注入** prompt；**写入闸门**仍仅显式保存（`#remember` 等）；召回含 **时间衰减** + **`matched_on`**。
- **通用知识 RAG（Phase 2 插件）**：默认关；本地 FTS/BM25 语料；**标注来源**；经 **B4** 润色；联网检索走 **A3** 且 **不入记忆库**（除非用户 `#remember`）。
- **混合推理**：云端显式触发；结果经 B4；润色不可用则硬降级。
- **安全**：B3 从 `configs/safety_replies/` 加载版本化话术。
- **数据可携带**：导出包 + `integrity` 占位。
- **评测**：50–100 条核心对话集（Phase 1 闭环后扩）。

---

## 四、MVP 基线设定

| 项目 | 设定 |
|------|------|
| 默认模式 | `local_only` |
| 记忆默认 | **关闭**；开启后 **仅显式保存** 写入；**开启后可自动 recall 注入** |
| 知识 RAG | **默认关闭**（Phase 2） |
| 云端接口 | 仅强推理，无联网检索（主线） |
| 自动路由上云 | 永不进主线 |
| 人设 / 配置 | `configs/` 为权威源 |
| 模型 | 默认 Qwen2.5-1.5B Q4_K_M；无本地文件时可下载（见 `tech-stack-v1.0.md`） |

---

## 五、Phase 0 现状与缺口

### 已完成

- 三层九域骨架、`shared` DTO、C2 SQLite/FTS/导出 IO、B2 CRUD/`#remember`/导出业务
- B3 规则分级 + **YAML 话术**（`configs/safety_replies/zh_v1.yaml`）、A1 CLI、A2 出站闸门、A3 Consent 落库
- **C1**：`LlamaCppBackend`、`check_model()` / `create_llama_backend()`、`check-model` 子命令（**Phase 1 步骤 1 已落地**）
- CI 双系统 + `check_imports` / `check_legacy_companion`

### 已闭合（Sprint 0～2）

- B3 YAML 话术（`configs/safety_replies/`）
- B1/B2 个人记忆 RAG：`recall()`、记忆块注入、`#remember` 显式写入
- C1 本地 GGUF：`LlamaCppBackend`、`check-model`
- **A2 编排**：`shell/ui_host/conversation_orchestrator.py`（`cli.py` 主循环委托 `run_turn`）
- **B4 规则润色 + 硬降级**：`core/local_reformatter/rule_reformatter.py`；云端失败不回传原文
- **A3 出站 HTTP**：`shell/outbound_manager/connector.py`；CLI `/cloud-reason`（Stub/真实 URL 可配置）
- B2 触发器 YAML：`configs/triggers.yaml` + `on_explicit_save`
- 验收：`scripts/full_acceptance.py`、`scripts/gpu_acceptance.py`

### 明确缺口（Sprint 4 及以后）

| 缺口 | 域 | 说明 |
|------|-----|------|
| 项目总览入口 | 文档 | Sprint 4.0 → [`PROJECT_STATUS.md`](./PROJECT_STATUS.md) |
| 记忆摘要草稿-确认 | B2 | Sprint 4.2，`on_summarize_request`，规则优先，默认关 |
| 可执行评测 ≥50 | 评测 | Sprint 4.4（与 note 类 fixture 分列统计） |
| Windows 逻辑验收 CI | 工程 | Sprint 4.5 → `acceptance_logic.yml` |
| CUDA / 性能基线文档 | C1 运维 | Sprint 4.1 → [`inference-cuda.md`](./inference-cuda.md) |
| PyInstaller / 本地 WebUI | A1 / 工程 | **Sprint 6 进行中** → [`sprint-6-plan.md`](./sprint-6-plan.md) |

**已闭合（Sprint 3～5）**：知识 RAG、Docker、fixture 51+、记忆草稿、可选向量（`embedding.yaml` 默认关）、[`sprint-5-plan.md`](./sprint-5-plan.md)。

联网知识检索：**不做**（宪章：仅 A3 + 显式同意；本地知识库优先）。

---

## 六、Phase 1 开发路线图

**目标**：本地对话闭环 + **个人记忆 RAG** + 安全话术文件化 + 可解释召回。

| 步骤 | 任务 | 模块 | 完成标准 | 状态 |
|------|------|------|----------|------|
| 1 | C1 稳固与健康检查 | C1 | GGUF 加载、`generate`、`check_model` | **已完成** |
| 2 | B2 `recall()` + 衰减 + `matched_on` | B2 | 每轮可召回；结果含解释字段 | **已完成** |
| 3 | B1 `assemble_reply()` + **自动注入记忆块** | B1 | 装配 prompt 调 C1；召回块注入 | **已完成** |
| 4 | CLI 经 B1 真实推理 | A1 | 默认 B1→C1；尊重记忆开关 | **已完成** |
| 5 | B3 话术 YAML 化 | B3 | 从 `configs/safety_replies/` 加载 | **已完成** |

### Phase 1：个人记忆 RAG（已确认，必做）

**产品承诺**：「我记得你说过……」——只引用**用户已显式保存**的记忆，零静默写入。

| 规则 | 说明 |
|------|------|
| **写入闸门** | 仅 `#remember`、显式保存命令等；**不**根据闲聊自动写入 |
| **读取闸门** | 用户开启记忆（`/memory on` 或引导开启）后，**每轮**对用户输入调用 `B2.recall()` |
| **注入方式** | B1 将 recall 结果格式化为参考块注入 prompt，**非**命令模型编造 |
| **可解释** | 每条命中含 `matched_on`；可与 `get_memory_explanation()` 共用元数据 |
| **编辑生效** | 删改记忆后**下一轮**装配刷新（宪章已冻结） |

**验收用例（摘要）**：

1. `#remember` 后相关提问 → 回复体现内容且可查 `matched_on`。  
2. 记忆关 → 无 recall、无注入。  
3. 未 `#remember` 的内容 → 不出现在 recall。  
4. `/memory del` 后下一轮不再注入该条。

### Phase 1 完成后的系统状态

- 本地 GGUF 按人设回复（经 B1）  
- 危机话术来自 YAML  
- 记忆：**可读、可编、可解释、可自动召回注入**（在开关打开时）

---

## 七、Sprint 3（已完成，2026-05）

**实施计划（评审冻结）**：[`sprint-3-plan.md`](./sprint-3-plan.md)

| 子项 | 状态 |
|------|------|
| 3.0 文档同步 | **已完成** |
| 3.1 本地知识 RAG（`knowledge.db`） | **已完成** |
| 3.2 Docker | **已完成** |
| 3.4 评测 50+ | **已完成** |
| 3.3 向量 | **已砍** |

---

## 七-B、Sprint 4（已完成，2026-05）

**项目入口**：[`PROJECT_STATUS.md`](./PROJECT_STATUS.md)  
**实施计划（评审冻结）**：[`sprint-4-plan.md`](./sprint-4-plan.md)

| 子项 | 状态 |
|------|------|
| 4.0 `PROJECT_STATUS.md` + README | **已完成** |
| 4.5 Windows/Ubuntu 逻辑验收 CI | **已完成** |
| 4.1 CUDA / 性能基线文档 | **已完成** |
| 4.2 记忆草稿 → 确认（规则优先） | **已完成** |
| 4.3 知识运维文档（不进主路径） | **已完成** |
| 4.4 可执行 fixture ≥50 | **已完成** |

---

## 七-C、Sprint 5（已完成，2026-05）

**实施计划**：[`sprint-5-plan.md`](./sprint-5-plan.md) · [`memory-embedding.md`](./memory-embedding.md)

| 子项 | 状态 |
|------|------|
| 5.0 文档同步 | **已完成** |
| 5.1 可选向量召回（哈希袋，默认关） | **已完成** |
| 5.2 `stress_test.py` | **已完成** |
| 5.3 GPU 耗时 WARN | **已完成** |
| 5.4 评测 + full_acceptance | **已完成** |

---

## 七-D、Sprint 6（已冻结，2026-05）

**实施计划**：[`sprint-6-plan.md`](./sprint-6-plan.md)

| 子项 | 状态 |
|------|------|
| §零 Sprint 5 收口 | **已完成** |
| 6.0 文档同步 | **已完成** |
| 6.1 PyInstaller PoC（Echo only） | 待开始 |
| 6.2 Flask WebUI（127.0.0.1） | 待开始 |
| 6.3 打包运行时约定 | 待开始 |
| 6.4 冒烟 + WebUI 20 轮手动基线 | 待开始 |
| 6.5 executable ≥80 | 待开始（可选） |

---

## 八、Phase 2 展望（历史分组；与 Sprint 2/3 对应）

*本节为早期规划快照；Sprint 2/3 的最新状态见第五节「已闭合 / 明确缺口」及 [`sprint-3-plan.md`](./sprint-3-plan.md)。*

### 7.1 记忆深化

- 触发器注册表（`on_summarize_request` 等，默认关）  
- `embedding` 字段可选启用（仍优先可解释 FTS）

### 7.2 通用知识 RAG（插件化 + 本地优先）

**原则**：不把陪伴主路径变成「全知百科」；**个人记忆 RAG 优先做到极致**。

| 约束 | 要求 |
|------|------|
| 默认 | **关闭**；`knowledge` 模式或 `/search-knowledge` |
| 索引 | **本地** SQLite FTS / BM25；离线语料（如维基摘要、安全手册）；核显可跑 |
| 来源 | 回复**必须标注出处**，用户可核对 |
| 润色 | `answer_after_search` 时经 **B4**；默认仅列片段则不过 B4（见 sprint-3-plan） |
| 审计 | 本地检索写审计表；联网须 **A3 + Consent Artifact** |
| 与记忆隔离 | **搜索结果默认不入** `memory_chunks`（除非用户 `#remember`） |

### 7.3 联网检索（极度谨慎）

- 每次搜索 = **独立受审事件**（A2 + A3）  
- 搜索历史可删除、可审计  
- 作为**高级可选项**，非 MVP/Phase 1 主线  

### 7.4 工程与其它

- ~~A3 真实 HTTP；B4 规则润色 + 硬降级~~（**Sprint 2 已完成**）  
- ~~A2 `ConversationOrchestrator`；`cli.py` 变薄~~（**Sprint 1 已完成**）  
- 评测 50–100 条（**Sprint 3.4**）；**Docker** 锁版本 + 模型/语料 volume（**Sprint 3**，见 `tech-stack-v1.0.md`）  
- PyInstaller 便携 exe（Phase 3）；本地 WebUI 壳（127.0.0.1）

---

## 九、维护纪律

1. 不得违反宪章六原则。  
2. CI 硬门禁须通过。  
3. **`configs/`** 为配置权威源；Docker 为运行时版本权威源（规划）。  
4. 新功能同步评测/fixture。  
5. 架构变更先改 `architecture_v1.0.md`，再改本文与 `tech-stack-v1.0.md`。

---

## 十、文档关系

| 文件 | 角色 |
|------|------|
| `architecture_v1.0.md` | 宪章原则（权威） |
| `tech-stack-v1.0.md` | 技术栈 v1.0（已敲定） |
| `architecture-and-roadmap-v1.0.md` | 本文：Phase + RAG + 缺口 |
| `sprint-3-plan.md` | Sprint 3 可执行计划（评审冻结） |
| `sprint-4-plan.md` | Sprint 4 可执行计划（评审冻结） |
| `PROJECT_STATUS.md` | 项目总览与冷启动（推荐入口） |
| `inference-cuda.md` | CUDA 安装与性能基线 |
| `sprint-5-plan.md` | Sprint 5 可执行计划 |
| `memory-embedding.md` | 可选记忆向量说明 |
| `sprint-6-plan.md` | Sprint 6 可执行计划（评审冻结） |
| `roadmap.md` | 产品方向历史清单 |
| `architecture-charter-v1.md` | 旧文件名跳转 |
