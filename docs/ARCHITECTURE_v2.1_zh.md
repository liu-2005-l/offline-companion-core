# Offline Companion · 开发思路与架构 v2.1（中文 · 权威）

> **版本**：v2.1 · **日期**：2026-06-18（审查修正版）  
> **历史基线**：[`architecture_v1.0.md`](./architecture_v1.0.md)（只读，冲突以本文为准）  
> **英文**：[`ARCHITECTURE_v2.0_en.md`](./ARCHITECTURE_v2.0_en.md)（文件名保持 v2.0，内容已同步）  

> **扩展开发**：[`SKILL_DEV_GUIDE`](./SKILL_DEV_GUIDE_v1.0_zh.md) · [`PLUGIN_DEV_GUIDE`](./PLUGIN_DEV_GUIDE_v1.0_zh.md)  
> **用户**：[`USER_MANUAL`](./USER_MANUAL_v1.0_zh.md)  
> **代码未对齐项**：[`_TEMP_NEXT_STEPS_2026-06-12.md`](./_TEMP_NEXT_STEPS_2026-06-12.md)（临时）

---

## 一、核心原则

1. **陪伴优先**：人设锁稳定；输出经 B1 装配，**B4 为最后闸门**。
2. **扩展为次**：Skill / Plugin / Tool 不污染主路径延迟与信任。
3. **记忆透明**：可编辑、可导出、可解释召回（`matched_on`）；`active/cancelled` 生命周期。
4. **隐私第一**：默认本地；**禁止静默上云**；B/C `check_imports` 硬拦网络库。
5. **出站可审计**：A2 许可 + A3 Consent Artifact。
6. **硬项同权**：安全话术、评测、导出与功能同权重。
7. **大脑与身体分离**：Agent 核心（B/C + A2 编排）负责任务理解、规划与分解；行动执行委托给独立 Skill 沙箱（agent-toolbox），实现「大脑」与「身体」的解耦。

---

## 二、系统分层（Agent 内核）

| 层 | 包路径 | 模块 | 网络 |
|----|--------|------|------|
| **A 策略壳** | `shell/` | A1 UI、A2 策略、A3 出站 | 仅 A3 |
| **B 陪伴核** | `core/` | B1 人格会话、B2 记忆、B3 安全、B4 润色 | 禁止 |
| **C 算力 IO** | `runtime/` | C1 推理、C2 存储（向量写入先落 SQLite vector_queue 表 WAL 日志，后台异步更新索引；Embedding 模型变更时提供 reindex 命令重建全量向量） | 禁止 |
| **横切** | `shared/` | DTO / 异常 | — |

**依赖**：`A1→A2→B→C`；禁止 `B→A`、`C→A`、`C→B`。  
**A1/A2 通信固化**：A1 桌面壳与 A2 核心之间全部通过本地 HTTP API（127.0.0.1）交互，禁止跨进程直接函数调用。  
**B/C** 禁止 `import` 网络库；白名单：`shell/outbound_manager/connector.py`。  
**B/C 不感知 UI、不感知 Skill/Plugin/Tool 扩展加载细节**（扩展编排仅在 A 层）。  
**B/C 层通过统一消息总线（Message Bus）与 A 层通信**，仅发送/接收标准化消息（BaseMessage），不关心传输层协议。所有跨层通信统一使用 BaseMessage 格式（含 `role`、`content`、`meta`、`timestamp`），无论底层传输是函数调用、HTTP 还是消息队列，消息结构保持一致。`content` 字段支持 `text`、`image_url`、`audio_buffer` 等类型。当前 MVP 仅实现 `text`，其余类型为协议层占位，供后续多模态 Skill 接入。

BaseMessage Schema 与消息总线抽象接口均放入 `shared/` 横切层，所有层均可依赖。A 层负责实现 MessageRouter 与传输层，B/C 层仅面向 `shared/` 中的接口收发消息，完全不感知实现细节。

**消息总线工程约定**：默认超时 30s，失败重试 1 次，异常通过 BaseMessage 的 `error` 字段透传，序列化统一使用 JSON。写操作消息须携带 `idempotency_key`，MessageRouter 在重试前检查是否已执行过相同 key 的操作，防止重复执行。读操作无此限制。

### 单轮陪伴主路径

```text
用户输入 → B3 安全（阻断 → 固定话术）
         → [S8+] A2 动态沙箱 / 会话间隔
         → B2 recall（记忆 on；仅 active）
         → B1 assemble_reply → [S8+] 上下文压缩（异步）
         → C1 generate → B4 → 落库
```

### 复杂任务路径

```text
用户复杂目标 → A2 PlanOrchestrator
  ├─ 任务分解：将目标拆解为有序步骤序列（Step 1 → Step 2 → Step 3）
  ├─ 依赖管理：声明步骤间的数据依赖（Step 2 需要 Step 1 的输出）
  ├─ 状态追踪：每个步骤的状态（pending / running / done / failed）
  ├─ 错误恢复：步骤失败时的重试策略或降级路径
  └─ 上下文传递：为每个任务创建独立的 TaskContext，存储中间结果
```
TaskContext：一个临时的、与任务绑定的数据空间，Skill 执行时读写此上下文，任务完成后可选择性地将关键结果写入 B2 记忆（`#remember`），其余丢弃。PlanOrchestrator 调用 Skill 时仍走 A3 Consent，Skill 仍运行在独立进程，B/C 层不感知计划的存在。

---

## 三、Skill / Plugin / Tool 严格划分

> **区分轴**：修改对象 → 加载路径 → 安全模型 → 审计路径。

| 类型 | 定位 | 修改对象 | 运行位置 | 安全策略 | 审计 |
|------|------|----------|----------|----------|------|
| **Skill** | 能力扩展 | Agent **能做什么** | 独立进程（localhost API） | 进程沙箱 + Consent | **A3** |
| **Plugin** | 体验优化 | Agent **交互形态**（UI） | 桌面壳 WebView（JS/CSS） | CSP + Bridge 限制 | **前端日志** |
| **Tool** | 轻量功能 | Agent **可调用函数集** | Agent 进程内 Python | builtin / certified / external | **A2 三态** |

### 约束细则

- **Skill 不碰 UI**：只经 localhost API 返回数据；**禁止** `ui_contributions`。
- **Plugin 不改能力**：不能增加 Agent 能力，只改变已有功能的交互；经 `window.bridge.call_skill` 调 Skill。
- **Tool 不独立存在**：非独立进程；**无运行时注册入口**；`builtin` 官方 Tool 可运行在主进程，需严格代码审计；第三方轻量能力统一迁移为微型 Skill（独立进程 + localhost API），`external` 仅 `configs/tools_external.yaml`（需显式启用，默认关闭）；结果**不进记忆库**。当前版本兜底措施：external Tool 在 `configs/tools_external.yaml` 中默认 `enabled: false`，需用户显式启用并确认风险提示后才生效。S9 收尾前完成所有 external Tool → 微型 Skill 迁移，届时移除 external 入口。
- **Skill 可联网**：声明 `cloud_inference` / `network_egress` 后走 A3（`LOCAL_ONLY` 硬拒）。
- **agent-toolbox 超级 Skill**：一个运行在 Docker 沙箱中的独立 Python 服务，集成浏览器自动化（Playwright）、代码执行、文件系统操作和网络请求能力。Agent 核心（大脑）通过 A2 编排器调用它（身体）执行具体动作，全程受 A3 Consent 保护。
- **消息队列模式**：agent-toolbox 与核心的通信默认使用 HTTP，但支持升级为基于 ZeroMQ 或 nanomsg 的消息队列模式。消息队列模式下，Skill 只负责发布消息到指定主题，A2 层 `MessageRouter` 作为消息代理负责路由；长时间任务的结果和进度更新通过队列异步推送，不阻塞当前对话流。B/C 层不感知通信模式的切换。
- **agent-toolbox 支持两种运行模式**：Docker 模式（生产环境，隔离性高）和 Native 进程模式（开发调试，安装门槛低）。用户安装时若 Docker 不可用，自动降级为 Native 模式，Consent 弹窗提示隔离性差异。
- **Docker 不可用时的极致体验**：启动 agent-toolbox 时自动检测 Docker 状态。若未安装或未运行，自动切换 Native 模式，并在底栏显示提示「沙箱未启用（直接在系统上运行）」。不弹窗阻断用户操作，但保留手动切换到 Docker 模式的入口。
- **Native 模式安全提示**：Native 模式 Consent 弹窗使用橙色/红色边框标注「此模组将直接在您的系统上运行，可能访问您的文件」。安装时 installer 检查 manifest 是否声明 `network_egress`，并提示用户确认。该提示逻辑属于 A3 Consent 生成阶段，不涉及 B/C 层改动。
- **每个 Skill 使用独立 Python 虚拟环境**（`extensions/installed/<skill-name>/.venv/`），避免依赖冲突。Skill manifest 声明依赖，安装时自动创建 venv 并 `pip install`。
- **依赖安全**：Skill 的 `requirements.txt` 需锁定依赖哈希值（`package==version --hash=sha256:...`）。安装时 installer 校验哈希，不匹配则拒绝安装并提示用户。安装完成后自动生成 SBOM（软件物料清单），存放在 `extensions/installed/<skill-name>/sbom.json`，供用户审计。
- **Skill 可声明 `output_mode: "raw"`**（如代码生成、数据分析、agent-toolbox 执行结果），此时 B4 仅做格式安全检测，不注入人格润色。
- **统一存放**：`{data_root}/extensions/installed/<name>/`；清单文件名因类型而异（见下表）。
- **统一管理**：设置页或右下角菜单启用/禁用；用户统称 **「模组」**；内部分流加载器（绝不混用）。
- **Skill API 鉴权**：宿主启动 Skill 时注入一次性随机 API Key，Skill 服务端必须校验 `Authorization` 请求头中是否携带该 Key。端口采用动态随机分配，禁用固定端口。invoker 调用时附加来源校验，仅接受主进程 PID 的连接。
- **Native 模式文件系统沙箱**：Native 模式下默认限制 Skill 文件访问范围为 `extensions/installed/<skill-name>/` 目录。如需访问外部路径（如 `exports/`），须在 manifest 中声明 `file_access` 权限并列出具体路径，经 A2 策略检查 + A3 Consent 确认后才放行。高风险 Skill（如 agent-toolbox）在 Native 模式下默认禁用文件操作、网络等高危能力，需用户手动授予。实现方式：A2 层在调用 Skill 前校验请求路径前缀，拦截超出 `extensions/installed/<skill-name>/` 的访问；Native 模式下通过 Python `os.path` 模块做路径规范化后再比对，防止 `../` 穿越。隔离强度说明：仅 Docker 模式提供进程级强制隔离（cgroups + 网络命名空间）；Native 模式为声明式安全 + 审计兜底，文件沙箱仅对 A2 层调用的标准文件 API 生效，无法拦截 Skill 进程内直接调用的系统 API。Native 模式的网络安全依赖开发者自律与上架扫描，没有系统级强制手段。用户在安装 Native 模式 Skill 时，Consent 弹窗需明确提示此差异。
- **agent-toolbox 作为基础能力平台**：提供标准化的文件操作、浏览器自动化、网络调用、代码执行 API，其他 Skill 通过宿主代理调用其能力，无需自行实现高危操作。所有高危操作统一收口到 agent-toolbox 审计，避免生态碎片化和重复的安全审计成本。
- **空闲回收与白名单**：通用 Skill 进程 10 分钟无新请求自动退出释放资源；agent-toolbox 等高频核心 Skill 单独配置 30 分钟超时或常驻选项。
- **单实例复用**：同一 Skill 的多次调用复用同一进程，崩溃时重启；同时运行 Skill 进程默认最多 3 个，超出排队。
- **风险等级自动判定**：manifest 只声明权限（network_egress / file_access / code_execution），policy 根据权限组合自动计算 risk_level（命中任一高危权限 → high）。禁止 Skill 自行声明风险等级。
- **高风险强制 Docker**：Native 模式下，high risk Skill 被 policy 硬拒绝启用，仅 Docker 模式可运行。

### 内部分流（系统视角）

| `type` | 清单文件 | 加载器 | 包路径（规划） |
|--------|----------|--------|----------------|
| `skill` | `manifest.json` | A2 `skill_manager` | `shell/skill_manager/` |
| `plugin` | **`plugin.json`** | A1 `plugin_loader` | `shell/ui_host/plugin_loader`（S8） |
| `tool` | `manifest.json` | A2 `tool_registry` | `shell/` + `companion-core/tools/`（S9+） |

Plugin 形态：WebView 内 JS/CSS 片段 + `ui_contributions`；详见 [`PLUGIN_DEV_GUIDE`](./PLUGIN_DEV_GUIDE_v1.0_zh.md)。

详情：Skill → [`SKILL_DEV_GUIDE`](./SKILL_DEV_GUIDE_v1.0_zh.md)；Plugin → [`PLUGIN_DEV_GUIDE`](./PLUGIN_DEV_GUIDE_v1.0_zh.md)。

---

## 四、模组商城（分发渠道 · 非唯一入口）

商城同时服务 **下载用户** 与 **创作者**；**本地文件夹加载是必备调试能力**，商城是可选分发渠道。

### 4.1 用户界面

| 约束 | 说明 |
|------|------|
| 入口 | 侧栏或设置中的 **「模组商城」**（当前侧栏占位，Sprint 8 激活 UI） |
| 首页 | 默认 **社区精选** |
| 分类 | **[全部] [能力] [交互] [工具]** ↔ Skill / Plugin / Tool |
| 卡片 | 统一 UI：名称、描述、评分、安装状态 |
| 操作 | 一键 **安装 / 卸载**；启用/禁用在设置或模组菜单（与类型无关） |
| 安装体验 | 用户点击安装后，下载、解压、创建 venv、安装依赖全自动完成，进度在卡片上以进度条展示。安装完成后模组自动启用，无需手动操作。依赖安装失败时，卡片显示「一键修复」按钮，自动重试或提示用户手动干预 | 待做 |
| 延迟加载 | 安装后不立即启动进程和加载模型，首次调用 Skill 时才启动。安装时仅完成文件解压和依赖安装，不占用额外资源 | 待做 |
| 内置模组 | 官方预置 3 个杀手级 Skill：① 本地代码解释器（Docker 沙箱，复用 agent-toolbox）；② 私人知识库助手（调用 RAG API）；③ 自动化生活管家（调用 PlanOrchestrator）。用户首次打开商城即可看到 | 待做 |
| 首次启动引导 | 首次打开商城时弹出浮层引导：「点击安装即可自动配置，无需手动操作。安装后默认开启基础功能，高级功能需手动确认。」 | 待做 |
| 助理模板 | 官方预设 4 套助理模板（高效办公 / 生活管家 / 学习陪伴 / 情绪陪伴），用户首次启动时选择，后续可在设置中切换。每套模板包含预设人设、推荐模组清单、默认提醒规则 | 待做 |

### 4.2 分发与安全

| 约束 | 说明 |
|------|------|
| 发布 | 开发者发布到 **skill-market 独立仓库**；商城索引自动更新 |
| 下载 | 经 **A3 Consent**；落盘 `extensions/installed/<name>/` |
| 安全扫描 | 上架前自动校验：清单 schema、文件完整性、依赖声明 |
| 信任等级 | **社区认证** vs **个人发布**，供用户决策 |

### 4.3 创作与本地加载

| 约束 | 说明 |
|------|------|
| 本地加载 | 开发者将模组文件夹 **手动放入** `extensions/installed/`，重启或刷新即生效 |
| 结构一致 | 本地目录 = 商城下载包 = 发布包（**本地能跑，发布即用**） |
| 模板仓 | `skill-template`、`plugin-template` 独立仓库（Sprint 8） |
| 清单规范 | Skill → `manifest.json`；Plugin → **`plugin.json`** |

**系统分流**：安装后按 `type` + 清单文件名走 §三 加载器；Skill 详情见 [`SKILL_DEV_GUIDE`](./SKILL_DEV_GUIDE_v1.0_zh.md)，Plugin 见 [`PLUGIN_DEV_GUIDE`](./PLUGIN_DEV_GUIDE_v1.0_zh.md)。

---

## 五、内置能力（非扩展 Plugin）

以下为 **B/C 层已交付能力**，不通过 `extensions/` manifest 加载：

| 能力 | 模块 | 说明 |
|------|------|------|
| 个人记忆 RAG | `core/memory_lifecycle/` | `#remember`、FTS、衰减、可解释召回；**混合检索**：记忆召回结合向量语义搜索 + BM25 关键词匹配 + SQLite FTS5 全文检索，三路召回后融合排序。AI 回答时附带引用标记（如 [1] [2]），用户可点击跳转到原文片段 |
| 通用知识 RAG | `core/knowledge_rag/` | 独立 `knowledge.db`；默认关；支持冷热知识分离——热知识（近期文档、今日待办）常驻内存或 SQLite FTS5，毫秒级召回；冷知识（旧日记、旧邮件归档）放入磁盘向量库，仅在深度复盘时检索。RAG 能力以独立服务形式暴露 API，供 Skill（如 novel-writer）调用，实现知识复用 |
| 可选记忆向量 | `configs/memory/embedding.yaml` | 默认 `enabled: false`；支持冷热分离——最近 N 天记忆（热数据）常驻内存或 SQLite FTS5 快速索引，旧记忆（冷数据）归档到磁盘，仅在显式 `#recall` 或深度搜索时加载。热数据窗口大小在 `embedding.yaml` 中配置。默认阈值：热数据窗口默认 30 天，冷数据归档阈值 90 天，均在 `embedding.yaml` 中配置。向量扩展采用 sqlite-vec；性能基线：10 万条记忆下召回延迟 < 50ms；向量索引构建全异步，不阻塞主流程。 |

运维与导入见 [`USER_MANUAL`](./USER_MANUAL_v1.0_zh.md) 与 [`PLUGIN_DEV_GUIDE`](./PLUGIN_DEV_GUIDE_v1.0_zh.md) 中「内置能力」交叉引用（Plugin 指南主文为 WebView 扩展）。

---

## 六、Agent 应用本体共识

### 6.1 桌面壳（A1）

| 项 | 共识 | 状态 |
|----|------|------|
| 技术 | pywebview + HTML/CSS/JS；127.0.0.1；进程内 orchestrator | ✅ |
| 布局 | 侧栏 + 主区 + 底栏（VS Code 式） | ✅ |
| 侧栏 | 会话/人格/模组/记忆/设置；PoC 仅会话激活 | ✅ 模组占位 |
| 底栏 | 隐私、记忆开关、模型状态 | ✅ |
| 生命周期 | 关窗→托盘；单实例 | ✅ |
| UI | 樱花粉；Consent Codex 卡片 | ✅ |
| 开发宿主 | Flask `web` 非产品验收 | ✅ |
| 硬件检测 | 安装前自动检测 GPU 显存 / RAM / 磁盘；显存 ≥8GB 推荐全功能模式，4-6GB 提示部分高级功能受限（如 IdleThink、CosyVoice），<4GB 推荐纯 CPU 模式 + 磁盘向量优化 | 待做 |
| 诚实提示 | 开启主动思考功能（IdleThink、GoalManager）需 ≥6GB 显存；不满足时在设置中灰显该选项并标注「当前硬件不支持」 | 待做 |
| 状态可视化 | IdleThink 后台运行时，托盘图标或角落小人使用呼吸灯效果；调用 Skill 时显示「正在执行任务」动画；长时间无交互时小人进入「待机」姿态。用户通过这些微交互感知 AI 状态，无需查看日志 | 待做 |
| 空闲检测 | A1 负责检测用户空闲状态（N 分钟无交互），通过事件通知 A2 触发 IdleThink 循环 | 待做 |

### 6.2 A2 策略

**A2 内部模块调用顺序**：每个请求进入 A2 层后，按以下顺序经过各模块处理：

```text
用户输入 / 系统事件
  → A2 Router LLM（意图路由：聊天 / 查资料 / 执行代码）
    → A2 Policy（动态沙箱 + 会话间隔 + LOCAL_ONLY 检查）
      → A2 Consent（出站许可检查，仅需出站时触发）
        → A2 skill_manager（调用目标 Skill）
          → A2 invoker（执行 Skill + 熔断检查）
            → A2 PlanOrchestrator（复杂任务分解，可选）
              → A2 GoalManager（长期目标评估，可选）
                → A2 AttentionAwareness（提醒过滤 + 注意力感知）
                  → A2 ResourceArbitrator（系统资源检查）
                    → A2 MessageRouter（消息路由到 B/C 层或 UI）
```

- 每个模块可跳过（如简单聊天不经过 PlanOrchestrator）。
- 模块间通过统一 BaseMessage 传递上下文，不共享可变状态。
- 此顺序为逻辑顺序，实现时各模块可独立启用/禁用。

**前置规则过滤器**：Router LLM 之前先过规则过滤器。当前会话无活跃任务、无 Skill 调用记录、用户输入长度 < 50 字 → 直接走短路链路（A2 透传 → B3 → B2 → B1 → C1 → B4），跳过所有复杂模块。

**StateManager**：A2 层单一状态数据源（基于 SQLite + 内存缓存），只存状态不做业务逻辑，所有判断、计算留在各自模块。

**事件驱动通信**：A2 内部模块间改为发布/订阅事件（复用 BaseMessage + 消息总线），不直接函数调用。

**中间件流水线**：每个 A2 模块实现 handle(message, next) 接口，启用就加入流水线，不启用就跳过。

**单职责字段修改**：每个中间件只能修改 message 中自己负责的字段（如 Policy 只改 policy_result，PlanOrchestrator 只改 task_steps），不碰其他模块字段。后续拆分时按字段直接划走模块。

| 项 | 共识 | 状态 |
|----|------|------|
| 动态沙箱 | 临时约束注入 prompt；不进记忆；本轮/今天/时长 | S8+ |
| 会话间隔 | B2 `last_active_at`；装配前注入 | S8+ |
| LOCAL_ONLY | 硬拒 `network_egress` / `cloud_inference` | ✅ Skill policy |
| Tool 三态 | ALLOW / ASK / DENY（PermissionEngine 远期） | S9+ Tool |
| 前置规则过滤器 | 无活跃任务 + 无 Skill 调用 + 输入 < 50 字 → 短路链路 | S7 收尾 |
| StateManager | SQLite + 内存缓存，只存状态不做业务逻辑 | S9 |
| 事件驱动通信 | A2 内部模块间发布/订阅事件，不直接函数调用 | S9 |
| 中间件流水线 | 每个模块实现 handle(message, next)，启用加入、不启用跳过 | S9 |
| 单职责字段修改 | 每个中间件只改自己负责的字段，不碰其他模块字段 | S9 |

### 6.3 B2 记忆

| 项 | 共识 | 状态 |
|----|------|------|
| 写入 | 唯一 `#remember`；压缩摘要可删 | ✅ 闸门 |
| `memory_type` | `fact` / `habit` / `preference` / `context_summary` | 待做 |
| `status` | `active` / `cancelled`；召回仅 active | 待做 |
| 习惯取消 | 冲突→标 cancelled，不新增条目 | 待做 |
| 时间戳 | `memory_chunks`、`messages` 均 `created_at` | 部分 |
| 衰减 | 越近越高；远期降权不归零 | ✅ |
| 压缩摘要 | `fidelity`、`round_range`、`compression_batch`（int，如 `26061101`） | 待做 |
| 压缩原则 | 基于原始对话；不二次压缩；按轮次区间 | 待做 |
| 优先级 | 用户事实 > Agent 人设 > 会话历史 | ✅ |

### 6.4 B1 上下文压缩（S8+）

- **触发**：token 超窗口 **80%** → 压至 **60%**。
- **保留**：人设铁律 + 近 **N** 轮原文 + 本轮召回记忆块。
- **执行**：**异步**，不阻塞当前轮回复。
- **摘要入库**：`memory_chunks`，`memory_type=context_summary`，用户可删。

### 6.5 B3 与 A2 沙箱

- **B3**：系统硬边界；`configs/safety_replies/`；用户不可改。
- **A2 沙箱**：用户临时约束；「今天」→ 沙箱，「以后/永远」→ 习惯记忆。

### 6.6 A3 Consent

Codex 卡片；樱花粉；`purpose_type` 见 Skill 指南（含 `skill_*` 四类）。

**Native 模式强化提示**：Consent 弹窗使用全橙色边框 + 醒目风险条 + 大白话文案 + 手动勾选「我已知晓风险」+ 二次确认按钮。

**设置页安全标识**：所有 Native 模式 Skill 在列表中常驻橙色「无隔离」标签，底栏常驻安全状态提示。

### 6.7 A2 PlanOrchestrator（S9）

任务规划与执行监控核心，将用户复杂目标拆解为可执行步骤序列。

| 项 | 共识 | 状态 |
|----|------|------|
| 任务分解 | 将目标拆解为有序步骤序列（Step 1 → Step 2 → Step 3） | 待做 |
| 依赖管理 | 声明步骤间的数据依赖（Step 2 需要 Step 1 的输出） | 待做 |
| 状态追踪 | 每个步骤的状态：pending / running / done / failed | 待做 |
| 错误恢复 | 步骤失败时的重试策略或降级路径；每个步骤可声明 `idempotent`（是否幂等），幂等步骤重试时复用已有结果，非幂等步骤跳过直接重试或要求用户确认 | 待做 |
| TaskContext | 临时数据空间，Skill 执行时读写，任务完成后可选写入 B2 记忆 | 待做 |
| 与 A3 关系 | 调用 Skill 时仍走 A3 Consent，B/C 层不感知计划存在 | 待做 |

**PlanNotebook**：PlanOrchestrator 的前端呈现——用户可见的计划管理 UI 界面（桌面壳侧栏或设置中），用于查看任务进度、暂停/恢复/取消计划。

### 6.8 A2 GoalManager（S9）

长期目标管理子系统，让 Agent 从「被动响应」走向「主动关心」。

| 项 | 共识 | 状态 |
|----|------|------|
| 目标存储 | 用户长期目标存于 B2 记忆，`memory_type: goal` | 待做 |
| 进度评估 | 定期评估目标进度（何时检查、检查什么） | 待做 |
| 触发提醒 | 检测到触发条件时，通过 B1 装配 prompt 主动提及 | 待做 |
| 频率控制 | 主动提醒频率硬上限（如每小时最多一次），用户可关闭 | 待做 |
| 提醒决策 | 引入效用函数：Utility = Value_of_Reminder - Cost_of_Distraction。低效用提醒在用户专注时自动降级（弹窗 → 托盘图标闪烁），高效用提醒（用户显式设定的紧急提醒）不受限制 | 待做 |
| 负反馈降权 | 用户关闭某类型提醒一次，该类型权重 ×0.5；两周内无同类提醒触发则权重恢复至 1.0；最低权重不低于 0.1 | 待做 |
| 紧急提醒仅用户标记 | 禁止模型/效用函数自行判断「紧急」，只有用户手动标记为「紧急」的待办/提醒才可突破静默期 | 待做 |

### 6.9 A2 IdleThink 循环（S9）

后台主动思考循环，依赖 GoalManager 驱动。

```text
空闲检测 → 用户 N 分钟无交互
  → 检查是否有活跃的长期目标
  → 评估当前上下文是否与目标相关
  → 决定是否生成主动提醒 / 建议 / 问题
  → 如果决定提醒 → 通过 B1 装配主动消息 → 在 UI 中呈现
```

空闲检测逻辑由 A1 桌面壳负责，检测到用户 N 分钟无交互后通过事件通知 A2 触发 IdleThink。C 层仅提供无状态 generate(prompt) 接口。

关键约束：
- 主动提醒的频率必须有上限（如每小时最多一次），且用户可以关闭。
- IdleThink 读取本地数据库不算出站，隐私模式不应禁止它。但如果用户关闭了「记忆开关」，IdleThink 不应访问 B2 记忆。
- IdleThink 产生的主动提醒如需通过 agent-toolbox 获取外部信息（如「监控网页价格」），仍须走 A3 Consent。
- 这与「陪伴优先」不冲突——主动关心是陪伴的高级形态，不是骚扰。
- **B4 闸门**：所有主动消息必须完整走 B1 人格装配 + B4 润色，A2 只负责「要不要提醒」和「核心信息」，不负责措辞语气。
- **默认关闭 + 渐进解锁**：所有主动能力默认全关闭；用户手动开启后先只开放托盘图标提醒，连续 7 天无负反馈才解锁弹窗提醒。

**分级降级策略**：根据硬件能力自动选择 IdleThink 驱动模式，用户无感知。

| 模式 | 硬件条件 | 驱动方式 |
|------|----------|----------|
| 高配模式 | 显存 ≥8GB | LLM 驱动的 IdleThink，完整推理能力 |
| 中配模式 | 显存 4-6GB | 混合规则引擎 + 轻量 LLM（如 Phi-3），规则引擎处理常见场景（连续打字 2 小时 → 休息提醒），LLM 处理复杂判断 |
| 低配模式 | 显存 <4GB | 仅使用规则引擎，不调用 LLM。规则引擎基于预定义模板（如时间、活动时长、日程匹配），确定性输出 |

### 6.10 C 层 JobScheduler（S8）

后台任务调度器，管理长时间运行、定时、延迟和事件监听任务。

| 项 | 共识 | 状态 |
|----|------|------|
| 定时任务 | Cron-like，如「每天早上 8 点备份数据」 | 待做 |
| 延迟任务 | 如「5 分钟后提醒我开会」 | 待做 |
| 事件监听任务 | 如「监控某个网页价格变化」 | 待做 |
| 长时间运行任务 | 如「帮我下载这个 50GB 的文件」 | 待做 |
| Skill 集成 | Skill 通过标准 API 向 JobScheduler 注册后台任务 | 待做 |
| 持久化 | 任务状态持久化到 SQLite，Agent 重启后可恢复 | 待做 |
| UI 不阻塞 | 所有后台任务异步执行，通过事件通知 UI（完成/失败/进度更新） | 待做 |
| Skill 存活检查 | 触发任务前先通过 skill_manager 检查目标 Skill 是否运行；已停止则标记为 failed，生成 `source: TOOLBOX` 错误记录 | 待做 |
| 任务心跳 | 每个运行中的任务定期更新心跳时间戳；Agent 重启后检查心跳超时的任务，标记为 `failed` 或 `retry` | 待做 |
| 调度算法 | 首批采用队列式（FIFO），后续版本评估抢占式优先级调度的必要性 | 待定 |
| 暂停恢复条件 | ResourceArbitrator 解除资源紧张状态后，JobScheduler 按暂停时间顺序恢复任务（先暂停的先恢复） | 待定 |

### 6.10.1 统一错误代码规范（S8）

贯穿 A/B/C 层的标准化错误结构，每个错误携带 `source`（来源层）和 `recoverable`（是否可恢复）标签。

| 字段 | 说明 |
|------|------|
| `code` | 唯一错误码，如 `E_SKILL_NETWORK_TIMEOUT` |
| `source` | 错误来源层：`A2` / `B3` / `B4` / `C1` / `SKILL` / `TOOLBOX` |
| `recoverable` | `true` / `false` |
| `user_message` | 给用户的本地化文案 |
| `dev_message` | 给开发者的堆栈或上下文 |

**约束**：
- 核心模块（A/B/C）每个模块错误码控制在 10-20 个以内，不过度细化。错误码是给恢复逻辑用的，不是给日志用的——日志应使用堆栈和上下文。
- Skill 返回的错误必须包含 `error_code` 字段，否则 invoker 自动包装为 `E_SKILL_UNHANDLED_ERROR`。

**已定义错误码**：

| 错误码 | 来源 | 可恢复 | 用户消息 |
|--------|------|--------|----------|
| `E_DOCKER_UNAVAILABLE` | TOOLBOX | 是 | Docker 环境不可用，已自动切换为轻量模式。部分高级隔离功能暂不可用。 |
| `E_SKILL_UNAUTHORIZED` | SKILL | 否 | 模组授权失败，请检查权限设置。 |

### 6.10.2 熔断机制（S8）

A2 invoker 为每个 Skill 维护 `failure_count`。连续失败 N 次（默认 3）后自动熔断，后续调用直接返回 `E_SKILL_CIRCUIT_OPEN`，不再实际调用 Skill。熔断状态在 N 分钟后（默认 5）自动恢复为半开状态探测。

**半开探测失败处理**：立刻重回熔断状态，熔断时间翻倍（如 5→10→20 分钟，上限 1 小时）；失败计数保留，不重置。连续 3 次半开探测均成功后，熔断状态完全解除，失败计数清零。

### 6.11 A2 AttentionAwareness（S9）

与 GoalManager 并列的注意力感知模块，确保「主动关心」不侵扰用户。

| 项 | 共识 | 状态 |
|----|------|------|
| 静默期检测 | 通过 agent-toolbox 获取前台应用状态（全屏？游戏？视频会议？）；深夜时段自动降低提醒等级 | 待做 |
| 提醒分级 | ① 低优先级：仅侧边栏气泡或托盘图标变色；② 中优先级：系统原生通知；③ 高优先级：弹窗+声音（仅用户显式设定的紧急提醒） | 待做 |
| 抑制输出 | 用户忙碌时 IdleThink 产生的提醒不入 B1 装配，写入待办队列，空闲时呈现 | 待做 |
| 隐私边界 | 启用需显式独立 Consent，弹窗告知「此模组需要读取您的系统活动状态（如是否全屏、是否在输入文字），用于判断是否适合发送提醒。不会记录或上传任何屏幕内容。」；设置页提供独立开关，关闭后不影响其他 IdleThink 能力 | 待做 |
| 场景静默 | 检测到全屏程序（游戏、视频会议）、深夜时段（23:00-7:00），静默所有非紧急提醒，降级为托盘红点 | 待做 |
| 频率硬锁 | 主动提醒每小时 ≤1 次，每天 ≤3 次，用户可调整但上限不可突破 | 待做 |
| 负反馈硬降权 | 用户关闭/忽略同类型提醒 2 次 → 7 天内不触发；用户回复中检测到「别提醒了」「吵」「不用管」等语义负反馈（复用 B3 层检测能力），同步生效 | 待做 |

### 6.12 A2 ResourceArbitrator（S9）

多进程资源仲裁器，防止 llama.cpp + Docker + Playwright 同时运行时 OOM。

| 项 | 共识 | 状态 |
|----|------|------|
| 前台优先 | C1 生成长文本时，自动暂停 JobScheduler 中 `low_priority` 后台任务 | 待做 |
| Docker 硬限制 | agent-toolbox 容器设置 `--memory=1g --cpus=1`（基线：Playwright + Python 解释器 ≈ 800MB） | 待做 |
| 降级策略 | 可用内存低于阈值（<500MB）时 IdleThink 自动暂停，托盘图标显示「资源紧张」 | 待做 |
| JobScheduler 预留 | S8 的 JobScheduler 每个任务带 `priority` 和 `resource_requirement` 字段 | 待做 |
| 硬件基准测试 | Sprint 8 补充硬件基准测试，确定各档位合理阈值；GPU 显存通过 `nvidia-smi` / `rocm-smi` 精准获取 | 待做 |
| 临时默认值 | 内存阈值默认 500MB，显存阈值默认 2GB（保守值，覆盖大多数 8GB 显卡 + 7B 模型的场景），Sprint 8 硬件基准测试后调整 | 待做 |

### 6.13 A1 DevTools & Auto-Eval（S8）

内置开发者工具与自动化评测系统。

| 项 | 共识 | 状态 |
|----|------|------|
| 开发者模式 | 桌面壳增加「开发者模式」开关，打开后侧边栏新增「消息监视器」，实时显示 A/B/C 层流转的 JSON 消息 | 待做 |
| Skill 拖拽编排 | 开发者模式下支持 Skill 拖拽编排——用户直接在 UI 上把「输入 → 技能A → 技能B → 输出」连起来，生成组合 Skill | 待做 |
| 自动化评测 | `Evaluator` 组件：每次 IdleThink 或 GoalManager 做出决策后，自动记录「预期结果」和「实际结果」，量化「主动关心是否变成了骚扰」 | 待做 |
| `check_imports` 增强 | 增加运行时网络模块替换（`socket`/`urllib` 强制抛出异常）+ 禁用 `exec`/`eval`/`importlib.import_module` | 待做 |
| 人设可视化编辑 | 用户在设置中通过表单（而非编辑 YAML）修改助理人设：性格描述、语气风格、回复长度偏好等，修改后实时生效 | 待做 |
| 提醒规则配置面板 | 用户在设置中通过可视化界面配置提醒规则：提醒类型、频率、时段偏好、静默期等，无需理解效用函数和权重算法 | 待做 |

### 6.14 A2 Router LLM & Self-Reflection（S9）

LLM 驱动的意图路由与自我反思能力。

| 项 | 共识 | 状态 |
|----|------|------|
| Router LLM | 引入轻量 Router LLM（如 Phi-3），专门判断用户意图：聊天（走 B1）、查资料（走 RAG）、执行代码（走 Toolbox）。替代正则匹配和 Keyword 检测，处理模糊边界。Router LLM 也为微型 Skill（独立进程），与第三方 Skill 同等隔离。 | 待做 |
| Self-Reflection | 每天凌晨或会话结束时，自动调用 LLM 总结今日对话，生成 N 条新的 `#remember` 事实写入 B2。写入必须遵守写入闸门原则（`#remember` 唯一通道），生成的事实需用户确认后才入库，写入前调 B3 安全分级，写入后标记 source: reflection。确认交互路径：每天首次打开 Agent 时，在对话区顶部以温和提示条展示「我回顾了昨天的对话，有 N 条想记住的事，要看看吗？[查看] [忽略]」。用户点击「查看」后展开待确认记忆列表，逐条确认/编辑/删除。不弹窗打断，不静默入库。 | 待做 |

### 6.15 Plugin 安全隔离（S8）

| 项 | 共识 | 状态 |
|----|------|------|
| DOM 隔离 | Plugin JS 运行在 Shadow DOM 隔离环境，仅能操作自身声明的 UI 节点 | 待做 |
| 事件权限 | 全局事件监听需单独申请权限，默认禁止 | 待做 |
| Bridge 白名单 | 每个 Bridge API 独立声明可接受的参数列表（参数名 + 类型 + 值域）。越权拦截时，Bridge 返回标准化错误 `E_PLUGIN_UNAUTHORIZED`，写入前端日志，不阻塞 UI 但提示用户「插件尝试越权操作，已被拦截」 | 待做 |

---

## 七、语音链路（规划 · Sprint 8 示例）

| 链路 | 形态 | 说明 |
|------|------|------|
| **TTS** | Skill `cosyvoice-tts`（`type:skill`，`permissions:[]`） | CosyVoice 本地；显存 ≥6GB 推荐 |
| **TTS UI** | Plugin `voice-output` | 设置里开关；回复自动播；无日常按钮 |
| **ASR** | Skill `asr-service` | 本地识别服务 |
| **ASR UI** | Plugin `voice-input` | 输入区麦克风；识别填入输入框；用户确认后发送 |

设置/菜单仅管理启用禁用，非功能日常入口。

---

## 八、多模态交互（远期探索 · Sprint 10+）

| 方向 | 形态 | 说明 |
|------|------|------|
| **全局悬浮窗** | Plugin + agent-toolbox | 通过 pywebview overlay 技术实现屏幕取词、即时翻译等浮窗交互，调用 agent-toolbox 获取屏幕上下文 |
| **注意力预测** | AttentionAwareness 扩展 | 通过鼠标轨迹和窗口切换模式预测用户注意力焦点，在低打扰场景下主动提供上下文相关的帮助（如「需要我帮你总结这个网页吗？」）。需独立 Consent，不记录或上传屏幕内容 |

## 九、AgentScope 对比（约束性参考）

**可借鉴（远期）**

- A2 **Middleware 洋葱链**：沙箱 → 隐私 → Skill 路由（非当前 Sprint）。
- **PermissionEngine 三态**：Consent 扩展 ALLOW / ASK / DENY。
- **Plan Mode**：PlanNotebook 可参考 AgentScope `PlanModeManager` 接口。

**本仓库护城河（不可放弃）**

1. B/C `check_imports` 架构级禁网。
2. 记忆透明：`active/cancelled` + `memory_type` + 习惯冲突 + 衰减。
3. **B4 润色器**为所有输出最后闸门。
4. Skill **独立进程 + localhost 锁定 + API Key 宿主注入**。
5. **agent-toolbox 外骨骼**：所有「行动」经独立 Docker 沙箱 Skill 执行，不污染核心进程；A3 Consent 为每步操作提供可审计闸门。
6. **主动关心有边界**：IdleThink 频率硬上限 + 用户可关闭；GoalManager 不越俎代庖。

---

## 十、架构不足与应对

| 不足 | 应对 | 优先级 | 时间 |
|------|------|--------|------|
| 复杂任务无编排 | PlanOrchestrator + TaskContext | **高** | S9 |
| 长期目标无驱动 | GoalManager + IdleThink | 中 | S9 |
| 后台任务无调度 | JobScheduler | **高** | S8 |
| 主动提醒可能侵扰用户 | AttentionAwareness + 提醒分级 | **高** | S9 |
| 多进程资源争抢风险 | ResourceArbitrator + Docker 硬限制 | 中 | S9 |
| 错误溯源困难 | ErrorCode Schema + 熔断机制 | **高** | S8 |
| 向量与 SQLite 不一致 | 事务日志 + reindex 命令 | 低 | S9+ |
| Skill 依赖冲突 | venv 隔离 + manifest 声明依赖 | 中 | S8 |
| Docker 强制依赖摩擦 | Native 模式降级 + Consent 提示 | 中 | S8 |
| 跨扩展协调缺失 | Pipeline 编排器 | 低 | S9+ |
| 用户画像被动 | 被动画像层 | 低 | S9+ |
| 安全策略传递 | manifest CSP 占位 | 中 | 7.1 收尾 |
| 记忆库长期膨胀风险 | 向量冷热分离 + 归档策略 | 低 | S9+ |
| Skill 依赖供应链风险 | 哈希锁定 + SBOM 生成 | 中 | S8 |
| 知识库与记忆库索引未打通 | 冷热知识分离 + RAG API 化 | 低 | S9+ |
| 跨层通信格式不统一 | 统一消息总线 + BaseMessage Schema | 中 | S9 |
| 开发者调试手段单一 | DevTools + 消息监视器 + 拖拽编排 | 中 | S8 |
| 意图路由依赖规则匹配 | Router LLM + Self-Reflection | 中 | S9 |
| 降级路径缺测试覆盖 | 降级场景测试清单 + 回归脚本 | 中 | S8 |
| 大脑-身体通信延迟 | agent-toolbox 异步回调 + 结果缓存 | 中 | S8 |
| check_imports 可被动态导入绕过 | 运行时沙箱 + 禁用 exec/eval | **高** | S8 |
| Skill API 无鉴权 | 随机 Key + 动态端口 | **高** | S7.2 |
| Plugin 无 DOM 隔离 | Shadow DOM + Bridge 白名单 | **高** | S8 |
| Native 模式无沙箱 | 文件系统沙箱 + 高危能力默认禁用 | **高** | S8 |
| SQLite 向量性能未验证 | sqlite-vec + 性能基线 | 中 | S9+ |
| venv 资源指数级膨胀 | 共享依赖池（S9+ 探索）；MVP 保持独立 venv（安全优先） | 低 | S9+ |
| ResourceArbitrator 阈值无硬件基准 | 补充硬件基准测试 | 中 | S8 |
| 异步向量写入可能丢数据 | 同步更新 FTS + 检索时查询未索引队列 | 中 | S9+ |
| WAL 持久化与崩溃恢复 | WAL 写入后立即 fsync 落盘，启动时自动重放未完成的 WAL 记录 | 中 | S9+ |
| Tool 是架构级后门 | 第三方 Tool 改为微型 Skill | **高** | S9 |
| Skill 能力无法复用 | agent-toolbox 平台化 | 中 | S9 |
| Plugin 扩展点不足 | S8 同步实现 sidebar_panel/message_bubble/settings_section | 中 | S8 |
| 章节编号与状态标记混乱 | 全局枚举 + 重排编号 | 低 | 本次合并 |
| 非功能需求缺失 | 补充性能/稳定性/资源占用基线 | 低 | S8 |
| 测试体系无顶层设计 | 分层测试策略 + CI 流水线 | 低 | S8 |
| Native 模式安全依赖声明式约束而非进程级强制 | 文档明确标注隔离强度差异；高风险 Skill 推荐仅 Docker 模式 | 低 | S8 |
| 缺少零代码定制能力 | 助理模板 + 人设可视化编辑 + 提醒规则配置面板 | 中 | S9 |
| 跨端能力缺失 | 局域网 WebUI 接入（数据全在本地）→ 端到端加密多端同步 | 低 | S10+ |
| 模组开发门槛偏高 | 低代码脚手架 + 商城配套创作者工具 | 低 | S10+ |

---

## 十一、Sprint 边界

### 已闭合

Sprint 0～6.8；**7.1 ✅** `skill_manager` registry/policy + 收尾（`extensions/installed/`、`type` 分流、CSP/错误码占位）。

### Sprint 7（当前）

**第一批（安全地基，优先交付）**：

| 子项 | 内容 | 状态 |
|------|------|------|
| 7.1 | registry/policy + extensions/installed/ + type 分流 | 🔶 部分完成 |
| 7.2 | Consent `purpose_type` + API Key 宿主注入 + Skill API 鉴权（随机 Key + 动态端口） | 待做 |
| 7.8 | **运行时网络沙箱**（B/C 层 socket/urllib 替换 + 禁用 exec/eval/importlib） | 待做 |

**第一批收尾条件**：7.2 + 7.8 全部完成后，Sprint 7 安全地基即视为闭合 ✅。其余子项（7.3~7.9）可延续至 Sprint 8 第一批继续。

**Sprint 7 收尾补充**：
- 前置规则过滤器 + 短路路由
- risk_level 自动判定 + 高风险强制 Docker
- C1/C2 接口抽象 + API 版本前缀 + 响应格式标准化

**第二批（生态与体验，安全地基闭合后继续）**：

| 子项 | 内容 | 状态 |
|------|------|------|
| 7.3 | **skill-market 独立仓** MVP API | 待做 |
| 7.4 | novel-writer 独立 Skill + local_api | 待做 |
| 7.5 | `/skill` CLI + 显式路由 | 待做 |
| 7.6 | 评测 + check_imports 扩展 | 部分 |
| 7.7 | **agent-toolbox 超级 Skill MVP** | Docker 沙箱 + Playwright + 代码执行（依赖 7.2 + 7.4 先闭合） | 待做 |
| 7.9 | **错误码校验逻辑落地 + 基础熔断**（invoker failure_count + 半开恢复） | 待做 |

### Sprint 8

**第一批（安全与稳定性，优先）**：
- **Plugin 安全隔离**（Shadow DOM + Bridge 白名单 + 权限校验）
- **JobScheduler**（核心调度 + 持久化 + 心跳 + Skill 存活检查）
- **向量读写一致性修复**（检索时同时查 WAL 未索引队列）
- **ErrorCode Schema 完善**（补充 E_DOCKER_UNAVAILABLE 等）
- **venv 隔离 + Native 模式降级**
- **空闲回收 + 白名单 + 单实例复用 + 并发上限**

**第二批（体验与生态，后置）**：
- Plugin 动态加载器（`plugin_loader` + 前端 PluginLoader）
- 模组商城 UI
- CosyVoice + voice-output 示例
- 模板仓
- DevTools（开发者模式 + 消息监视器 + Skill 拖拽编排）
- 硬件体检
- 内置模组
- 四份核心 doc 定稿
- **Native 模式强化 Consent + 设置页安全标识**

### Sprint 9A（核心骨架）

Tool（`tool_registry` + 分级）；**PlanOrchestrator + TaskContext**；**PlanNotebook**；**消息队列升级**（agent-toolbox ZeroMQ/nanomsg 通信模式 + A2 MessageRouter）；**ResourceArbitrator**；**Tool 迁移收口**：S9 收尾前完成所有 external Tool → 微型 Skill 迁移，届时移除 external 入口。

> 9A 目标：先跑通复杂任务编排骨架，确保 PlanOrchestrator 能正确分解、执行和恢复任务。同步完成 Tool 后门封堵。

**Sprint 9 补充**：
- **StateManager + 事件驱动 + 中间件 + 单职责字段**

### Sprint 9B（软能力）

**GoalManager + IdleThink 循环**（被动画像的前置）；**AttentionAwareness**；**Router LLM + Self-Reflection**；桌面二次元小人；**UI 微交互**（呼吸灯 + 执行动画 + 待机姿态，与二次元小人并列）。

**Sprint 9B 补充**：
- **场景静默 + 频率硬锁 + 负反馈硬降权 + 语义负反馈 + 紧急仅用户标记 + B4 闸门 + 默认关闭渐进解锁**

| 子项 | 内容 | 状态 |
|------|------|------|
| 助理模板 | 4 套预设模板（高效办公/生活管家/学习陪伴/情绪陪伴），首次启动引导式选择 | 待做 |
| 人设可视化编辑 | 设置中通过表单修改人设，实时生效 | 待做 |

> 9B 目标：在 9A 骨架跑通后，叠加主动关心和注意力感知等软能力，降低调试复杂度。

### Sprint 10+（远期探索）

- **局域网 WebUI 接入**：手机/平板通过局域网访问同一台主机的助理，数据全在本地
- **低代码模组脚手架**：常见场景填参数生成 Skill/Plugin 包
- **跨端同步**：端到端加密多端同步，不经过中心服务器

---

## 十二、技术栈与数据目录

| 领域 | 选择 |
|------|------|
| 语言 | Python 3.11 |
| 推理 | llama-cpp-python + GGUF |
| 默认模型 | Qwen2.5-1.5B-Instruct Q4_K_M |
| 存储 | SQLite + FTS5 |
| 桌面 | pywebview + pystray |
| Skill 校验 | `pip install -e ".[skill]"` |
| 硬件检测 | 下载器 / 安装器内置；检测 GPU 显存、系统内存、可用磁盘 |
| 向量扩展 | sqlite-vec |
| 向量性能基线 | 10 万条记忆召回延迟 < 50ms |
| 推理接口抽象 | C1 推理抽象为 LLMBackend 接口，当前实现 LlamaCppBackend |
| 存储接口抽象 | C2 向量存储抽象为 VectorStore 接口，当前实现 SqliteVecStore |
| API 版本前缀 | 所有 HTTP 接口统一使用 /api/v1/ 前缀 |
| 响应格式标准化 | Skill 请求/响应统一封装为 { code, data, error } 结构 |

**不引入**：torch、langchain、chromadb、faiss、Electron、npm 构建链（Plugin 亦零构建）。

```text
{data_root}/
├── companion.db
├── knowledge.db              # 内置知识 RAG
├── configs/
├── models/
├── extensions/installed/     # 目标路径（模组统一目录）
│   ├── <skill-name>/
│   │   └── manifest.json
│   ├── <plugin-name>/
│   │   └── plugin.json
│   └── <tool-name>/
│       └── manifest.json
├── exports/
└── logs/
```

运维命令见 [`USER_MANUAL`](./USER_MANUAL_v1.0_zh.md)。

---

## 十三、文档体系

| 文档 | 读者 | 约束 |
|------|------|------|
| **ARCHITECTURE v2.1** | 开发者/架构师 | **冲突时以本文为准** |
| **SKILL_DEV_GUIDE** | Skill 开发者 | manifest、API、调试 |
| **PLUGIN_DEV_GUIDE** | 前端/全栈 | `ui_contributions`、Bridge |
| **USER_MANUAL** | 普通用户 | 零技术术语；截图示意 |
| **CHANGELOG** | — | 版本记录 |
| **architecture_v1.0** | 历史 | 只读基线 |

中文为权威源；英文为 AI 辅助翻译。关键术语：`Skill` / `Plugin` / `Tool` / `模组` 不混译。

配套交付（S8）：`skill-template`、`plugin-template` 独立模板仓库。

---

## 十四、维护

1. 架构/共识变更 → **本文** + CHANGELOG。  
2. 代码与文档冲突 → 先记 [`_TEMP_NEXT_STEPS`](./_TEMP_NEXT_STEPS_2026-06-12.md)，闭合后删。  
3. **禁止**在 `docs/` 新增未列于 [`README.md`](./README.md) 的正式文档类型（临时 `_TEMP_*` 除外）。
4. 状态标记枚举：
   - ✅ 已完成
   - 🔲 待做
   - 🔶 部分完成
   - 📅 S8+ / 📅 S9+ 标注计划 Sprint
   每个模块在 §六 中的状态表必须使用以上枚举值，禁止混用「待做」「S8+」「部分」等非标准标记。

---

## 十五、非功能需求基线

| 指标 | 目标值 | 测量方法 |
|------|--------|----------|
| 单轮陪伴响应延迟 | < 2s（本地 GGUF）/ < 5s（云端推理） | `full_acceptance` 计时 |
| 记忆召回延迟 | < 100ms（10 万条） | FTS 查询计时 |
| 向量召回延迟 | < 50ms（10 万条） | `sqlite-vec` 查询计时 |
| Skill 首次启动延迟 | < 3s（含 venv 激活） | invoker 启动计时 |
| 连续运行 24h 内存占用 | < 2GB（含 1 个本地模型） | 系统监控 |
| Skill 调用成功率 | > 99%（不含用户主动停止） | JobScheduler 统计 |
| 熔断触发误判率 | < 1% | invoker 日志统计 |
| IdleThink 侵扰投诉率 | < 5%（用户关闭功能视为投诉）；用户关闭提醒视为负反馈信号，GoalManager 自动降低该类型提醒权重 | Auto-Eval 统计 |

---

## 十六、测试体系

| 层级 | 范围 | 工具 | 频率 |
|------|------|------|------|
| **单元测试** | 所有模块核心函数 | `pytest` | 每次 commit |
| **集成测试** | A/B/C 层间调用链 + Skill 通信 | `pytest` + fixture | 每次 PR |
| **端到端测试** | 完整对话流 + Consent 流程 | `full_acceptance.py` | 每 Sprint 收尾 |
| **安全扫描** | `check_imports` + AST 扫描 + 运行时沙箱 | CI 门禁 | 每次 PR |
| **性能基准** | 非功能需求基线各项指标 | 独立脚本 | 每 Sprint 收尾 |
| **降级路径测试** | 熔断、Native 降级、资源紧张降级 | 降级场景测试清单 | Sprint 8 起每 Sprint |

**CI 门禁规则**：
- **分层依赖检查**：禁止 B 调 A、C 调 B 的 import，违反则 CI 不通过
- **安全扫描**：`check_imports` + AST 扫描 + 运行时沙箱，违反则 CI 不通过
- **单元测试**：设为强制门禁，不通过不准合入
- 以上规则在每次 PR 时自动执行，不满足任一条件则阻断合入

**Sprint 7 收尾前**：完成 CI 最小骨架搭建——分层依赖检查脚本 + pytest 门禁脚本，不要求全覆盖，但骨架必须跑通。Sprint 8 起逐步扩展覆盖率。
