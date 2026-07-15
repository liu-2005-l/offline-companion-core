# Offline Companion · 开发思路与架构 v2.4（中文 · 权威）

> **版本**：v2.3 · **日期**：2026-07-15（安全闭环修订）
> **历史基线**：[`architecture_v1.0.md`](./architecture_v1.0.md)（只读，冲突以本文为准）
> **英文**：[`ARCHITECTURE_v2.3_en.md`](./ARCHITECTURE_v2.3_en.md)（英文版同步中）

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
**B/C 层通过统一消息协议与 A 层通信**，仅发送/接收标准化消息（BaseMessage），不关心传输层协议。所有跨层通信统一使用 BaseMessage 格式（含 `role`、`content`、`meta`、`timestamp`），无论底层是函数调用、HTTP 还是消息队列，消息结构保持一致。`content` 字段支持 `text`、`image_url`、`audio_buffer` 等类型。当前 MVP 仅实现 `text`，其余类型为协议层占位，供后续多模态 Skill 接入。

**协议统一，实现按需选择**：
- **核心对话链路**：走同步实现（函数调用模拟），保证低延迟和可调试性
- **后台任务链路**：走异步实现（ZeroMQ 消息队列），不阻塞主对话

BaseMessage Schema 与消息总线抽象接口均放入 `shared/` 横切层，所有层均可依赖。A 层负责实现 MessageRouter 与传输层，B/C 层仅面向 `shared/` 中的接口收发消息，完全不感知底层是同步还是异步。

**已落地基础能力**：
- `BaseMessage` 统一协议 + 同步版 `MessageRouter` 最小路由骨架
- `StateManager` 基础三域封装（session / task / system）
- `runtime_sandbox` 运行时危险能力最小兜底
- `SkillInvoker` 基础熔断（连续失败计数 + 熔断态拦截）
- `check_imports` AST 分层门禁 + 直接执行入口修复
- 跨平台路径 / 编码 / 测试 fixture 兼容修复

**消息总线工程约定**：

| 约定 | 说明 |
|------|------|
| 默认超时 | 30s，超时后返回 `E_MESSAGE_TIMEOUT` |
| 失败重试 | 最多 1 次，重试前检查 `idempotency_key` 是否已执行 |
| 异常透传 | 通过 BaseMessage 的 `error` 字段传递，序列化统一使用 JSON |
| 写操作幂等 | 所有写操作消息必须携带唯一 `idempotency_key`，MessageRouter 执行前先查执行记录。重复 key 直接返回已有结果，不重新执行 |
| 会话级串行 | 同一会话的所有消息严格按顺序执行，禁止并发。跨会话消息可并行 |
| 死信队列 | 所有失败消息进入死信队列，持久化到 SQLite，提供人工补偿入口（CLI 命令或设置页） |
| 异步仅限后台任务 | JobScheduler 和 agent-toolbox 后台任务允许异步消息队列。核心对话链路保持同步调用 |
| 双队列物理隔离 | 同一会话拆两条队列：主对话队列（高优先级，严格串行）+ 后台任务队列（低优先级，可并发）。后台任务永远不能阻塞对话响应 |
| 后台任务优先级 | 后台任务队列与 ResourceArbitrator 联动：资源紧张时先暂停低优先级后台任务，高优先级保留 |
| 冲突优先级约定 | 主对话队列状态操作优先级永远高于后台任务；冲突时后台任务自动重试 3 次，失败进入死信队列，绝不阻塞主对话 |

**A 层语义封装**：所有 Skill/Tool 的具体函数名、参数名、API 细节，全部在 A 层完成组装后封装为能力描述，再注入发给 B 层的消息。B 层的系统提示词只包含人格描述和安全规则，绝对不出现具体工具名称或业务字段。新增 Skill 只需改 A 层配置，B 层代码零改动。语义转换做反向相似度校验，解析失败自动向用户补全信息，不盲调。

**CI 校验**：CI 增加 prompt 关键词扫描，B 层所有 prompt 模板文件禁止出现 Skill 名称、函数名、参数字段等实现细节，命中直接打回。新增解耦测试：新增一个 Skill 不改 B 层任何代码能正常调用，作为集成测试必过项。

### 单轮陪伴主路径

```text
用户输入 → B3 安全（阻断 → 固定话术）
         → [S8+] A2 动态沙箱 / 会话间隔
         → B2 recall（记忆 on；仅 active）
         → B1 assemble_reply → [S8+] 上下文压缩（异步）
         → C1 generate → B4 → 落库

> **云端模型路由分支**：若 AutoRouter 决策使用云端模型，生成环节将通过 A3 出站调用云端推理 Skill，结果返回后仍需经过 B4 闸门；LOCAL_ONLY 模式下保持原纯本地链路不变。
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

**说明**：本体交互和扩展加载严格分离，Skill / Plugin / Tool 不得混用注册通道。

### 约束细则

- **Skill 不碰 UI**：只经 localhost API 返回数据；**禁止** `ui_contributions`。
- **Plugin 不改能力**：不能增加 Agent 能力，只改变已有功能的交互；经 `window.bridge.call_skill` 调 Skill。
- **Tool 不独立存在**：非独立进程；**无运行时注册入口**；`builtin` 官方 Tool 可运行在主进程，需严格代码审计；第三方轻量能力统一迁移为微型 Skill（独立进程 + localhost API），`external` 仅 `configs/tools_external.yaml`（需显式启用，默认关闭）；结果**不进记忆库**。当前版本兜底措施：external Tool 在 `configs/tools_external.yaml` 中默认 `enabled: false`，需用户显式启用并确认风险提示后才生效。S9 收尾前完成所有 external Tool → 微型 Skill 迁移，届时移除 external 入口。
- **Skill 可联网**：声明 `cloud_inference` / `network_egress` 后走 A3（`LOCAL_ONLY` 硬拒）。
- **agent-toolbox 超级 Skill**：一个运行在沙箱中的独立 Python 服务，集成浏览器自动化（Playwright）、代码执行、文件系统操作和网络请求能力。Agent 核心（大脑）通过 A2 编排器调用它（身体）执行具体动作，全程受 A3 Consent 保护。
- **沙箱实例按调用方隔离**：不同 Skill 调用 agent-toolbox 分配独立沙箱实例，调用结束销毁，文件、进程、网络完全隔离，禁止共享运行时环境。
- **消息队列模式**：agent-toolbox 与核心的通信默认使用 HTTP，但支持升级为基于 ZeroMQ 或 nanomsg 的消息队列模式。消息队列模式下，Skill 只负责发布消息到指定主题，A2 层 `MessageRouter` 作为消息代理负责路由；长时间任务的结果和进度更新通过队列异步推送，不阻塞当前对话流。B/C 层不感知通信模式的切换。
- **agent-toolbox 支持三种运行模式**：Docker 模式（核心底座，进程级隔离）、CubeSandbox 模式（可选增强，KVM 硬件级隔离）和 Native 进程模式（兜底，仅低风险 Skill）。三种模式的隔离级别和启动速度对比如下：

  | 模式 | 定位 | 隔离级别 | 启动速度 | 单实例内存 | 适用场景 |
  |------|------|----------|----------|------------|----------|
  | **Docker**（核心底座） | 生产环境首选 | 进程级（cgroups + 网络命名空间） | 秒级 | ~50MB | 所有 Skill 默认运行模式 |
  | **CubeSandbox**（可选增强） | 用户主动安装后可选切换 | KVM 硬件级 | <60ms | <5MB | 用户主动安装 CubeSandbox 后可选切换 |
  | **Native**（仅限官方内置 Skill） | Windows/macOS 下仅限官方签名内置 Skill | 声明式（文件沙箱 + 审计兜底） | 零开销 | — | 仅限文件哈希校验通过的内置 Skill，第三方 Skill 禁止使用 |

  用户安装时自动检测可用模式，按 Docker → CubeSandbox（若已安装）→ Native 优先级自动选择。每次降级触发 Consent 弹窗，明确提示用户当前隔离强度变化。

- **CubeSandbox 不可用时的极致体验**：启动 agent-toolbox 时自动检测 Docker 可用性。若 Docker 不可用，降级 Native 模式。CubeSandbox 作为可选增强，用户主动安装后可在设置中切换。底栏显示当前隔离级别标识（CubeSandbox 绿色「硬件隔离」/ Docker 蓝色「进程隔离」/ Native 橙色「无隔离」）。不弹窗阻断用户操作，但保留手动切换模式的入口。
- **Native 模式安全提示**：Native 模式 Consent 弹窗使用橙色/红色边框标注「此模组将直接在您的系统上运行，可能访问您的文件」。安装时 installer 检查 manifest 是否声明 `network_egress`，并提示用户确认。该提示逻辑属于 A3 Consent 生成阶段，不涉及 B/C 层改动。
- **每个 Skill 使用独立 Python 虚拟环境**（`extensions/installed/<skill-name>/.venv/`），避免依赖冲突。Skill manifest 声明依赖，安装时自动创建 venv 并 `pip install`。
- **基础运行时共享**：Docker/CubeSandbox 提供系统级隔离和基础运行时（Python 版本、系统依赖），venv 只负责 Skill 自身的 Python 依赖。基础镜像只带 Python 标准库和通用依赖，Skill 专属依赖装在自身 venv 里，启动时挂载进沙箱。CubeSandbox 的 CoW 机制基于基础镜像做克隆，Skill venv 作为可写层，最大化共享只读数据。
- **依赖安全**：Skill 的 `requirements.txt` 需锁定依赖哈希值（`package==version --hash=sha256:...`）。安装时 installer 校验哈希，不匹配则拒绝安装并提示用户。安装完成后自动生成 SBOM（软件物料清单），存放在 `extensions/installed/<skill-name>/sbom.json`，供用户审计。
- **Skill 可声明 `output_mode: "raw"`**（如代码生成、数据分析、agent-toolbox 执行结果），此时 B4 仅做格式安全检测，不注入人格润色。
- **统一存放**：`{data_root}/extensions/installed/<name>/`；清单文件名因类型而异（见下表）。
- **统一管理**：设置页或右下角菜单启用/禁用；用户统称 **「模组」**；内部分流加载器（绝不混用）。
- **Skill API 鉴权**：宿主启动 Skill 时注入一次性随机 API Key，Skill 服务端必须校验 `Authorization` 请求头中是否携带该 Key。端口采用动态随机分配，禁用固定端口。invoker 调用时附加来源校验，仅接受主进程 PID 的连接。
- **Native 模式文件系统沙箱**：Native 模式下默认限制 Skill 文件访问范围为 `extensions/installed/<skill-name>/` 目录。如需访问外部路径（如 `exports/`），须在 manifest 中声明 `file_access` 权限并列出具体路径，经 A2 策略检查 + A3 Consent 确认后才放行。高风险 Skill（如 agent-toolbox）在 Native 模式下默认禁用文件操作、网络等高危能力，需用户手动授予。实现方式：A2 层在调用 Skill 前校验请求路径前缀，拦截超出 `extensions/installed/<skill-name>/` 的访问；Native 模式下通过 Python `os.path` 模块做路径规范化后再比对，防止 `../` 穿越。
- **内置 Skill 文件哈希校验**：所有内置 Skill 启动前做文件哈希校验，和官方预置的哈希值比对，不一致直接拒绝运行。Native 模式下强制开启此校验，Docker 模式下可选。不解决校验问题，仅靠「官方内置」的标签防不住本地文件篡改。
- **Native 模式系统调用级拦截**：Native 模式下补充系统调用级拦截，分平台实现：
  - **Linux**：使用 seccomp-bpf 限制系统调用白名单，只开放 Skill 声明权限对应的系统调用（如纯计算 Skill 只开放 read/write/exit 等基础调用，禁止 socket/clone/mount 等）。
  - **macOS**：使用 sandbox-exec 配置沙箱，限制文件系统访问、网络访问和进程创建。
  - **Windows**：使用 Job Object + 受限令牌，限制进程创建、文件系统访问和网络访问。
  系统调用级拦截在 Skill 进程启动时由 A2 层配置，Skill 进程内无法绕过。实现优先级：Linux seccomp-bpf 优先（Sprint 8），macOS 和 Windows 后续补充（Sprint 9+）。
- **Native 模式仅限纯计算类 Skill**：声明 `network_egress`、`file_access`、`code_execution` 中任一权限的 Skill，Native 模式下直接拒绝启动，不甩风险给用户。本地手动加载的 Skill 执行同等规则，调试模式单独开关确认后可临时放宽。用户安装时若 Docker 不可用且 Skill 包含上述权限，Consent 弹窗明确提示「此模组需要进程级隔离，当前环境无法满足，请安装 Docker 后重试」。
- **agent-toolbox 自身权限最小化**：agent-toolbox 自己的 manifest 也要声明权限（`network_egress` / `file_access` / `code_execution`），三类高危权限默认关闭。用户首次调用前必须单独 Consent 确认才能开启。它是能力平台，不是法外之地，自己也要遵守同一套权限规则。
- **宿主代理二次鉴权**：其他 Skill 调用 agent-toolbox 能力时，宿主代理必须做二次权限校验——调用方 Skill 的 manifest 声明了对应权限，才允许转发调用，没有就直接拒绝。agent-toolbox 的所有高危接口必须带上调用方 Skill ID，每一次调用走 A3 Consent 审计链路，和 Skill 直接调用的审计标准完全一致。
- **agent-toolbox 作为基础能力平台**：提供标准化的文件操作、浏览器自动化、网络调用、代码执行 API，其他 Skill 通过宿主代理调用其能力，无需自行实现高危操作。所有高危操作统一收口到 agent-toolbox 审计，避免生态碎片化和重复的安全审计成本。
- **空闲回收与白名单**：通用 Skill 进程 10 分钟无新请求自动退出释放资源；agent-toolbox 等高频核心 Skill 单独配置 30 分钟超时或常驻选项。
- **单实例复用**：同一 Skill 的多次调用复用同一进程，崩溃时重启；同时运行 Skill 进程默认最多 3 个（CubeSandbox 模式下可提升至 20 个），超出排队。
- **风险等级自动判定**：manifest 只声明权限（network_egress / file_access / code_execution），policy 根据权限组合自动计算 risk_level（命中任一高危权限 → high）。禁止 Skill 自行声明风险等级。
- **高风险默认 Docker**：Native 模式下，high risk Skill 被 policy 硬拒绝启用。Docker 模式下 high risk Skill 可运行。CubeSandbox 作为可选增强，用户主动安装后可在设置中切换。
- **CubeSandbox eBPF 网络策略**：CubeSandbox 的 CubeVS 组件可将 A2 Consent 中声明的域名白名单直接编译为 eBPF 过滤规则，在内核态强制执行。Skill 内部无法绕过此限制，实现 Consent 模型在基础设施层的技术兜底。即使 Skill 进程被攻破，网络出站仍受 eBPF 规则约束。
- **CubeSandbox CoW 文件系统**：CubeSandbox 的 CoW + reflink 机制用于模组加载优化。多个 Skill 共享同一份基础镜像的物理存储，只有写操作时才复制数据页。结合「延迟加载」设计，Skill 首次调用时从基础镜像秒级克隆出实例，大幅降低存储占用和启动延迟。
- **CubeSandbox 快照机制**：CubeSandbox 支持快照/克隆/回滚操作，与 PlanOrchestrator 的状态恢复机制天然契合。详见 §6.2.6。

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
| 安装体验 | 用户点击安装后，下载、解压、创建 venv、安装依赖全自动完成，进度在卡片上以进度条展示。安装完成后模组自动启用，无需手动操作。依赖安装失败时，卡片显示「一键修复」按钮，自动重试或提示用户手动干预 | 🔲 待做 |
| 延迟加载 | 安装后不立即启动进程和加载模型，首次调用 Skill 时才启动。安装时仅完成文件解压和依赖安装，不占用额外资源 | 🔲 待做 |
| 内置模组 | 官方预置 3 个杀手级 Skill：① 本地代码解释器（Docker 沙箱，复用 agent-toolbox）；② 私人知识库助手（调用 RAG API）；③ 自动化生活管家（调用 PlanOrchestrator）。用户首次打开商城即可看到 | 🔲 待做 |
| 首次启动引导 | 首次打开商城时弹出浮层引导：「点击安装即可自动配置，无需手动操作。安装后默认开启基础功能，高级功能需手动确认。」 | 🔲 待做 |
| 助理模板 | 官方预设 4 套助理模板（高效办公 / 生活管家 / 学习陪伴 / 情绪陪伴），用户首次启动时选择，后续可在设置中切换。每套模板包含预设人设、推荐模组清单、默认提醒规则 | 🔲 待做 |

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
| 可选记忆向量 | `configs/memory/embedding.yaml` | 默认 `enabled: false`；支持冷热分离——最近 N 天记忆（热数据）常驻内存或 SQLite FTS5 快速索引，旧记忆（冷数据）归档到磁盘，仅在显式 `#recall` 或深度搜索时加载。热数据窗口大小在 `embedding.yaml` 中配置。默认阈值：热数据窗口默认 30 天，冷数据归档阈值 90 天，均在 `embedding.yaml` 中配置。向量扩展采用 sqlite-vec；性能基线：10 万条记忆下召回延迟 < 50ms；向量索引构建全异步，不阻塞主流程。**WAL 强制 fsync**：WAL 写入后立即 fsync 落盘，再返回写入成功。**启动时先同步重放 WAL 未索引数据到内存队列**，重放完成前不提供召回服务。**主数据 + 向量索引双写**：写入成功以 SQLite 主库为准。向量索引异步更新，内存缓存未索引队列，召回时合并查询。**索引更新 + 队列移除原子执行**，结果按 ID 自动去重。**索引定期校验**：每小时比对主数据条数与向量索引条数，不一致自动增量修复。reindex 期间双索引过渡，不影响线上召回。 |

运维与导入见 [`USER_MANUAL`](./USER_MANUAL_v1.0_zh.md) 与 [`PLUGIN_DEV_GUIDE`](./PLUGIN_DEV_GUIDE_v1.0_zh.md) 中「内置能力」交叉引用（Plugin 指南主文为 WebView 扩展）。

---

## 六、Agent 应用本体共识

### 6.1 A1 桌面壳

| 项 | 共识 | 状态 |
|----|------|------|
| 技术 | pywebview + HTML/CSS/JS；127.0.0.1；进程内 orchestrator | ✅ |
| 布局 | 侧栏 + 主区 + 底栏（VS Code 式） | ✅ |
| 侧栏 | 会话/人格/模组/记忆/设置；PoC 仅会话激活 | ✅ 模组占位 |
| 底栏 | 隐私、记忆开关、模型状态、隔离级别标识 | ✅ |
| 生命周期 | 关窗→托盘；单实例 | ✅ |
| UI | 樱花粉；Consent Codex 卡片 | ✅ |
| 开发宿主 | Flask `web` 非产品验收 | ✅ |
| 硬件检测 | 安装前自动检测 GPU 显存 / RAM / 磁盘；显存 ≥8GB 推荐全功能模式，4-6GB 提示部分高级功能受限，<4GB 推荐纯 CPU 模式 + 磁盘向量优化 | 🔲 待做 |
| 诚实提示 | 开启主动思考功能（IdleThink、GoalManager）需 ≥6GB 显存；不满足时在设置中灰显该选项并标注「当前硬件不支持」 | 🔲 待做 |
| 状态可视化 | IdleThink 后台运行时，托盘图标使用呼吸灯效果；调用 Skill 时显示「正在执行任务」动画；长时间无交互时进入「待机」姿态 | 🔲 待做 |
| 空闲检测 | 检测用户 N 分钟无交互，通过事件通知 A2 触发 IdleThink 循环 | 🔲 待做 |

### 6.2 A2 策略编排层

#### 6.2.1 控制面与数据面拆分

A2 层内部严格拆分为控制面与数据面，职责完全隔离。

| 面 | 职责 | 包含模块 | 约束 |
|----|------|----------|------|
| **控制面** | 策略决策与意图判断 | Policy、AutoRouter、Router LLM、PlanOrchestrator、GoalManager、AttentionAwareness | 不直接操作数据存储，决策结果写入 message 专属字段 |
| **数据面** | 消息转发、状态持久化、流水线执行与资源调度 | skill_manager、invoker、MessageRouter、StateManager、JobScheduler、ResourceArbitrator | 不执行业务判断，所有状态读写通过 StateManager 统一 API |

**强制约束**：
- 数据面模块不得执行业务判断（如 invoker 不能自行决定是否允许出站）。
- 所有模块读写状态必须通过 StateManager 统一 API，禁止直接互调或跨模块读字段。
- 每个中间件只能修改 message 中自己专属命名空间的字段（如 Policy 只改 `policy_result`，PlanOrchestrator 只改 `task_steps`）。跨字段修改视为架构违规，CI 直接阻断。

#### 6.2.2 内部调用主链路

每个请求进入 A2 层后，按以下顺序经过各模块处理，简单请求可跳过非必要模块。

```
用户输入 / 系统事件
  → 前置规则过滤器（初筛意图）
    → A2 Router LLM（意图路由：聊天 / 查资料 / 执行代码，S9B 替代规则过滤器）
      → A2 Policy（动态沙箱 + 会话间隔 + LOCAL_ONLY 硬检查）
        → A2 AutoRouter（模型路由：本地 / 云端 / 混合）
          → A2 Consent 校验（云端路由/高危操作时触发）
            → A2 PlanOrchestrator（复杂任务分解，可选）
              → A2 skill_manager（匹配目标 Skill）
                → A2 invoker（执行 Skill + 熔断检查）
                  → A2 GoalManager（长期目标评估，可选）
                    → A2 AttentionAwareness（提醒过滤 + 注意力感知）
                      → A2 ResourceArbitrator（系统资源检查）
                        → A2 MessageRouter（消息路由到 B/C 层或 UI）
```

**约束说明**：
- 模块间通过统一 BaseMessage 传递上下文，不共享可变状态。
- 此顺序为逻辑顺序，实现时各模块可独立启用 / 禁用。
- PlanOrchestrator 负责调度多步骤任务，每一步 Skill 调用均通过 invoker 执行，遵守统一鉴权与熔断规则。

#### 6.2.3 前置规则过滤器

Router LLM 落地前的临时初筛方案，基于关键词 + 意图规则快速分流。
- 命中工具关键词（机票、酒店、查询、下载等）→ 走完整链路
- 命中闲聊关键词（你好、在吗等）→ 走短路链路
- 边界模糊请求强制走完整链路，宁可多耗性能，不能错判意图

**验收标准**：工具调用漏判率 < 0.1%，误判率 < 1%；短路链路识别到工具意图自动回退完整链路二次处理，不返回错误结果；上线前 100 条测试用例全量通过。

| 项 | 共识 | 状态 |
|----|------|------|
| 前置规则过滤器 | 关键词 + 意图规则判定，拿不准走完整链路 | ✅ S7 收尾 |

#### 6.2.4 Policy 模块

A2 层全局策略校验入口，所有请求必须经过 Policy 校验后方可进入后续链路。

| 项 | 共识 | 状态 |
|----|------|------|
| LOCAL_ONLY 硬拦截 | 硬拒 `network_egress` / `cloud_inference` 类能力 | ✅ Skill policy |
| 动态沙箱 | 临时约束注入 prompt；不进记忆；支持本轮 / 今天 / 自定义时长 | 📅 S8+ |
| 会话间隔 | 读取 B2 `last_active_at`，装配前注入上下文 | 📅 S8+ |
| Tool 三态管理 | ALLOW / ASK / DENY 三级权限控制 | 📅 S9+ |

#### 6.2.5 AutoRouter（智能模型路由 · S9A）

智能模型路由器，根据任务类型、复杂度、隐私需求和成本预算，自动决定使用本地模型还是云端模型。与 Router LLM 职责分离：**Router LLM 判断「做什么」，AutoRouter 决定「谁来做」**。

##### 核心组件

| 组件 | 职责 | 实现方式 |
|------|------|----------|
| **TaskProfiler** | 对用户输入做快照分析，输出 TaskProfile（任务类型、复杂度评分、所需工具、上下文长度、隐私敏感度） | S9A：规则引擎 + 关键词匹配；S10+：微型 LLM |
| **CostPredictor** | 根据 TaskProfile 和模型清单，预估不同模型的 token 花费、延迟和预期质量，输出 RoutingDecision | 基于 `configs/model_routing.yaml` 的静态成本表 |
| **决策引擎** | 综合隐私模式、复杂度阈值、成本预估，做出最终路由决策 | S9A：规则驱动；S10+：引入 ResourceArbitrator 资源状态反馈 |

##### 模型清单配置（`configs/model_routing.yaml`）

```yaml
models:
  - name: local-qwen-1.5B
    type: local
    cost_per_1k_tokens: 0
    latency_per_token_ms: 15
    max_tokens: 2048
    capabilities: ["chat", "simple_qa"]
  - name: deepseek-v4
    type: cloud
    cost_per_1k_tokens: 0.002
    latency_per_token_ms: 5
    max_tokens: 16384
    capabilities: ["code_generation", "complex_reasoning", "tool_use"]
    requires_consent: true
```

##### 决策流程

```
用户输入 → TaskProfiler 生成 TaskProfile
  → CostPredictor 预估各模型成本与延迟
    → 决策引擎判定：
      ├─ LOCAL_ONLY 模式 / 隐私敏感 → 强制本地模型
      ├─ 复杂度 < 阈值 + 本地能力匹配 → 本地模型
      ├─ 复杂度 ≥ 阈值 或 本地能力不足 → 推荐云端模型
      │   → 生成 purpose_type: cloud_routing 的 Consent 申请
      │   → 用户确认后走 invoker → 云端 Skill
      │   → 返回结果 → B4 润色与安全校验（B4 为最后闸门，云端结果不绕过）
      └─ 云端调用失败 → invoker 自动回退本地模型，提示用户结果可能降级
```

##### 关键约束

- **隐私优先**：LOCAL_ONLY 模式或任务隐私敏感时，直接跳过云端模型推荐；隐私敏感度判定复用 B3 安全模块的检测规则与关键词库。
- **Consent 审计**：每次云端路由决策生成独立 Consent Artifact，含预估 token 数、预估花费、推荐理由。
- **回退由 invoker 执行**：AutoRouter 只产出路由决策（含 fallback 模型），不参与实际调用；云端调用超时/失败时，复用 invoker 现有熔断机制。
- **能力标签统一**：`capabilities` 字段使用 `shared/` 层统一定义的枚举常量，与 Router LLM 意图分类、Skill 能力声明保持一致。
- **配置单一数据源**：`model_routing.yaml` 仅存放路由决策元数据，不读取 C1 层模型加载配置。

| 项 | 共识 | 状态 |
|----|------|------|
| 规则引擎版路由 | TaskProfiler + CostPredictor + 决策引擎 | 📅 S9A |
| 云端路由 Consent | 对接 A3 Consent 审计体系 | 📅 S9A |
| 失败自动回退 | 复用 invoker 熔断机制，失败回退本地模型 | 📅 S9A |
| 用户反馈学习 | 基于历史反馈个性化调整复杂度阈值 | 📅 S10+ |

#### 6.2.6 PlanOrchestrator（任务编排 · S9A）

任务规划与执行监控核心，将用户复杂目标拆解为可执行步骤序列并调度执行。

##### 核心能力

| 项 | 共识 | 状态 |
|----|------|------|
| 模板加载 | 支持从 JSON / YAML 模板加载预设计划 | 📅 S9A |
| 任务分解 | 将目标拆解为有序步骤序列（Step 1 → Step 2 → Step 3） | 📅 S9A |
| 依赖管理 | 声明步骤间的数据依赖，支持 DAG 编排 | 📅 S9A |
| 状态追踪 | 每个步骤状态：pending / running / done / failed | 📅 S9A |
| 错误恢复 | 步骤失败时的重试策略或降级路径；支持幂等步骤标记 | 📅 S9A |
| TaskContext | 临时数据空间，Skill 执行时读写，任务完成后可选写入 B2 记忆 | 📅 S9A |
| Consent 暂停恢复 | 高危步骤触发 Consent 时暂停执行，用户确认后恢复 | 📅 S9A |
| 生命周期控制 | 支持任务暂停/取消/恢复 | 📅 S9A |
| CubeSandbox 快照增强 | 执行步骤前做快照，失败可回滚（仅 CubeSandbox 模式可用） | 📅 S9A |

##### 关键约束

- 调用 Skill 时仍走 A3 Consent 流程，B/C 层不感知计划存在。
- 每一步 Skill 调用均通过 invoker 执行，遵守统一鉴权、熔断规则。
- 基础模式依赖 TaskContext + 幂等步骤实现错误恢复，不依赖沙箱快照特性；沙箱快照为可选增强。
- 前端呈现为 PlanNotebook，用于查看任务进度、暂停/恢复/取消计划。

#### 6.2.7 StateManager（状态中枢）

A2 层单一状态数据源，基于 SQLite + 内存缓存实现，只存状态不做业务逻辑，所有判断、计算留在各自模块。

##### 核心能力

| 项 | 共识 | 状态 |
|----|------|------|
| 三域统一入口 | session / task / system 三域划分，统一读写 API | 🔶 部分完成 |
| 域权限隔离 | 各域有明确读写权限，跨域读写 API 直接抛异常 | 📅 S9A |
| 乐观锁并发控制 | 所有状态修改带版本号，冲突自动重试，禁止直接覆盖 | 📅 S9A |
| 事件订阅机制 | 支持 subscribe / unsubscribe、通配符订阅；回调异常不影响主流程 | 🔶 部分完成 |
| 状态变更审计 | 所有状态变更记录操作者、时间、变更内容，持久化到 SQLite | 📅 S9+ |
| 物理隔离 | 状态域按域拆分独立 SQLite 文件 | 📅 S9+ |

##### 关键约束

- 所有模块读写状态必须经 StateManager DAO 层，CI 拦截直连数据库操作的代码。
- 仅负责状态存储与事件分发，不承载任何业务逻辑；空闲检测由 A1 负责，检测后发布事件到 StateManager，IdleThink 模块订阅事件自行触发。
- 事件命名与 payload 遵循 `shared/` 层统一规范，携带 trace_id、触发源、版本号。

#### 6.2.8 JobScheduler（后台任务调度 · S8）

后台任务调度器，管理长时间运行、定时、延迟和事件监听任务。

| 项 | 共识 | 状态 |
|----|------|------|
| 定时任务 | Cron-like 表达式，支持周期性任务 | 📅 S8 |
| 延迟任务 | 支持指定时间后触发执行 | 📅 S8 |
| 事件监听任务 | 支持条件触发类任务 | 📅 S8 |
| 长时间运行任务 | 支持大文件、长耗时任务后台执行 | 📅 S8 |
| Skill 集成 | Skill 通过标准 API 注册后台任务 | 📅 S8 |
| 持久化 | 任务状态持久化到 SQLite，Agent 重启后可恢复 | 📅 S8 |
| UI 不阻塞 | 所有后台任务异步执行，通过事件通知 UI 进度与结果 | 📅 S8 |
| Skill 存活检查 | 触发任务前校验目标 Skill 运行状态，异常则标记失败 | 📅 S8 |
| 任务心跳 | 运行中任务定期更新心跳，超时自动标记失败 | 📅 S8 |
| 调度算法 | 首批采用队列式（FIFO） | 📅 S8 |
| 暂停恢复 | ResourceArbitrator 解除资源紧张后，按暂停顺序恢复任务 | 📅 S8 |

#### 6.2.9 统一错误代码规范（S8）

贯穿 A/B/C 层的标准化错误结构，每个错误携带 `source`（来源层）和 `recoverable`（是否可恢复）标签。

##### 标准字段

| 字段 | 说明 |
|------|------|
| `code` | 唯一错误码，如 `E_SKILL_NETWORK_TIMEOUT` |
| `source` | 错误来源层：`A2` / `B3` / `B4` / `C1` / `SKILL` / `TOOLBOX` |
| `recoverable` | `true` / `false` |
| `user_message` | 给用户的本地化文案 |
| `dev_message` | 给开发者的堆栈或上下文 |

##### 核心错误码清单（首批）

| 分层 | 错误码 | source | recoverable | 用户消息示例 |
|------|--------|--------|-------------|--------------|
| A2 | `E_MESSAGE_TIMEOUT` | A2 | 是 | 当前请求超时，请稍后重试。 |
| A2 | `E_MESSAGE_DUPLICATE` | A2 | 是 | 请求已处理，已返回历史结果。 |
| A2 | `E_MESSAGE_ORDER_VIOLATION` | A2 | 否 | 同会话消息顺序异常，请刷新后重试。 |
| A2 | `E_POLICY_DENIED` | A2 | 否 | 当前请求触发策略规则，已阻断。 |
| A2 | `E_CONSENT_REQUIRED` | A2 | 是 | 该操作需要您的确认。 |
| A2 | `E_LOCAL_ONLY_DENIED` | A2 | 否 | 当前为本地模式，无法执行该请求。 |
| B3 | `E_CONTENT_VIOLATION` | B3 | 否 | 当前内容违反安全规则，已拦截。 |
| B4 | `E_OUTPUT_FORMAT_INVALID` | B4 | 是 | 输出格式校验未通过，已重新整理。 |
| B4 | `E_OUTPUT_POLICY_VIOLATION` | B4 | 否 | 输出内容触发安全规则，已拦截。 |
| C1 | `E_MODEL_LOAD_FAILED` | C1 | 否 | 本地模型加载失败。 |
| C1 | `E_MODEL_TIMEOUT` | C1 | 是 | 模型推理超时，请稍后重试。 |
| C1 | `E_MODEL_CONTEXT_OVERFLOW` | C1 | 是 | 上下文过长，已自动压缩后重试。 |
| SKILL | `E_SKILL_UNAUTHORIZED` | SKILL | 否 | 模组授权失败，请检查权限设置。 |
| SKILL | `E_SKILL_UNHANDLED_ERROR` | SKILL | 是 | 模组发生未处理错误，已记录。 |
| SKILL | `E_SKILL_CIRCUIT_OPEN` | SKILL | 是 | 模组暂时不可用，请稍后再试。 |
| TOOLBOX | `E_DOCKER_UNAVAILABLE` | TOOLBOX | 是 | Docker 环境不可用，已自动切换为轻量模式。部分高级隔离功能暂不可用。 |
| TOOLBOX | `E_TOOLBOX_SANDBOX_DENIED` | TOOLBOX | 否 | 沙箱策略拒绝了该操作。 |
| TOOLBOX | `E_TOOLBOX_RUNTIME_ERROR` | TOOLBOX | 是 | 基础工具运行时异常，请稍后重试。 |

**约束**：
- 核心模块每个模块错误码控制在 10-20 个以内，不过度细化。
- Skill 返回的错误必须包含 `error_code` 字段，否则 invoker 自动包装为 `E_SKILL_UNHANDLED_ERROR`。

#### 6.2.10 熔断机制（S8）

A2 invoker 为每个 Skill 维护失败计数，连续失败达到阈值后自动熔断。

| 项 | 共识 | 状态 |
|----|------|------|
| 基础熔断 | 连续失败 3 次自动熔断，直接返回错误 | 🔶 部分完成 |
| 半开探测 | 熔断到期后先发起无副作用健康检查，成功再放业务流量 | 📅 S8 |
| 指数退避 | 探测失败则熔断时间翻倍（5→10→20 分钟，上限 1 小时） | 📅 S8 |
| 错误分类统计 | 仅服务端可恢复错误计入熔断计数，客户端错误不计入 | 📅 S8 |
| 解除熔断 | 连续 3 次健康检查成功后正式解除，失败计数清零 | 📅 S8 |

**关键约束**：
- 熔断计数仅统计 `source: SKILL|TOOLBOX` 且 `recoverable: true` 的错误。
- 半开探测同样区分错误类型，客户端错误不算探测失败。

#### 6.2.11 ResourceArbitrator（资源仲裁 · S9）

多进程资源仲裁器，防止 llama.cpp + 沙箱 + Playwright 同时运行时 OOM。

| 项 | 共识 | 状态 |
|----|------|------|
| 前台优先 | C1 生成长文本时，自动暂停低优先级后台任务 | 📅 S9 |
| 沙箱资源限制 | Docker 模式单实例限制 `--memory=1g --cpus=1` | 📅 S9 |
| 并发上限动态调整 | CubeSandbox 模式最多 20 个并发，Docker 模式最多 3 个，Native 模式最多 1 个 | 📅 S9 |
| 降级策略 | 可用内存低于阈值时 IdleThink 自动暂停，托盘显示「资源紧张」 | 📅 S9 |
| 硬件基准测试 | 补充硬件基准测试，确定各档位合理阈值 | 📅 S8 |
| 临时默认值 | 内存阈值默认 500MB，显存阈值默认 2GB，基准测试后调整 | 📅 S8 |

#### 6.2.12 Router LLM & Self-Reflection（S9B）

| 项 | 共识 | 状态 |
|----|------|------|
| Router LLM | 轻量模型专门判断用户意图，替代规则过滤器，处理模糊边界；以微型 Skill 形式运行，与第三方 Skill 同等隔离 | 📅 S9B |
| Self-Reflection | 每日自动总结对话生成待确认记忆，经用户确认后写入 B2；遵守 `#remember` 唯一写入闸门 | 📅 S9B |

**关键约束**：
- Router LLM 输出意图标签使用 `shared/` 层统一定义枚举，与 AutoRouter、Skill 能力声明对齐。
- Self-Reflection 生成的记忆必须用户确认后才入库，不静默写入，不弹窗打断。

#### 6.2.13 GoalManager（长期目标管理 · S9B）

长期目标管理子系统，让 Agent 从「被动响应」走向「主动关心」。

| 项 | 共识 | 状态 |
|----|------|------|
| 目标存储 | 用户长期目标存于 B2 记忆，`memory_type: goal` | 📅 S9B |
| 进度评估 | 定期评估目标进度 | 📅 S9B |
| 触发提醒 | 检测到触发条件时，通过 B1 装配 prompt 主动提及 | 📅 S9B |
| 频率控制 | 主动提醒频率硬上限，用户可关闭 | 📅 S9B |
| 提醒决策 | 引入效用函数，低效用提醒自动降级展示级别 | 📅 S9B |
| 负反馈三级判定 | 强/弱/正三级反馈对应不同权重系数，语义负反馈做关键词 + 语义双重判断 | 📅 S9B |
| 紧急提醒仅用户标记 | 只有用户手动标记「紧急」的提醒才可突破静默期 | 📅 S9B |

#### 6.2.14 IdleThink 循环（S9B）

后台主动思考循环，依赖 GoalManager 驱动。

```
A1 检测用户 N 分钟无交互
  → 发布空闲事件
    → IdleThink 接收事件，检查是否有活跃长期目标
      → 评估当前上下文与目标相关性
        → 决定是否生成主动提醒
          → 如需提醒 → 通过 B1 装配 + B4 润色 → UI 呈现
```

**关键约束**：
- 所有主动消息必须完整走 B1 人格装配 + B4 润色，A2 只负责决策是否提醒与核心信息。
- 默认全关闭；用户手动开启后先只开放托盘图标提醒，连续 7 天无负反馈解锁系统通知，连续 30 天无负反馈解锁弹窗。
- 底栏提供一键全局静默按钮，静默状态持久化。
- 根据硬件能力自动降级驱动模式：显存 ≥8GB 用 LLM 驱动，4-6GB 用规则 + 轻量 LLM 混合，<4GB 纯规则引擎。

#### 6.2.15 AttentionAwareness（注意力感知 · S9B）

与 GoalManager 并列的注意力感知模块，确保主动关心不侵扰用户。

| 项 | 共识 | 状态 |
|----|------|------|
| 静默期检测 | 通过 agent-toolbox 获取前台应用状态；深夜时段自动降低提醒等级 | 📅 S9B |
| 提醒分级 | 低优先级侧边栏气泡 / 中优先级系统通知 / 高优先级弹窗 + 声音（仅用户标记紧急） | 📅 S9B |
| 抑制输出 | 用户忙碌时提醒写入待办队列，空闲时呈现 | 📅 S9B |
| 隐私边界 | 启用需独立 Consent，不记录不上传屏幕内容；设置页提供独立开关 | 📅 S9B |
| 场景静默 | 全屏程序、深夜时段静默非紧急提醒，降级为托盘红点 | 📅 S9B |
| 频率硬锁 | 主动提醒每小时 ≤1 次，每天 ≤3 次，上限不可突破 | 📅 S9B |
| 负反馈硬降权 | 用户关闭/忽略同类型提醒 2 次 → 7 天内不触发；语义负反馈同步生效 | 📅 S9B |

#### 6.2.16 A1 DevTools & Auto-Eval（S8）

内置开发者工具与自动化评测系统。

| 项 | 共识 | 状态 |
|----|------|------|
| 开发者模式 | 侧边栏新增消息监视器，实时显示 A/B/C 层流转的 JSON 消息 | 📅 S8 |
| Skill 拖拽编排 | 开发者模式下支持可视化组合 Skill 生成新模组 | 📅 S8 |
| 自动化评测 | 自动记录主动提醒决策的预期与实际结果，量化侵扰程度 | 📅 S8 |
| `check_imports` 增强 | 运行时网络模块替换 + 禁用 exec/eval/importlib 动态导入 | 📅 S8 |
| 人设可视化编辑 | 设置中通过表单修改助理人设，实时生效 | 📅 S8 |
| 提醒规则配置面板 | 可视化配置提醒规则，无需理解算法细节 | 📅 S8 |
| 基础门禁已落地 | `check_imports` AST 分层门禁、运行时沙箱最小兜底、pytest 门禁脚本 | 🔶 部分完成 |

### 6.3 A3 出站审计（Consent）

统一出站与权限审计入口，所有高危操作、网络出站、沙箱降级均生成可追溯的 Consent Artifact。

#### purpose_type 全量枚举

| `purpose_type` | 触发场景 | 审计字段 | 有效期 | 可复用 |
|----------------|----------|----------|--------|--------|
| `skill_network_egress` | Skill 声明联网能力 | `skill_id`、`domain_allowlist`、`reason` | 单次会话 | 否 |
| `skill_file_access` | Skill 声明外部文件访问 | `skill_id`、`path_allowlist`、`reason` | 单次会话 | 否 |
| `skill_code_execution` | Skill 声明代码执行能力 | `skill_id`、`runtime`、`reason` | 单次会话 | 否 |
| `skill_cloud_inference` | Skill 需要云端推理 | `skill_id`、`model`、`reason` | 单次会话 | 否 |
| `cloud_routing` | AutoRouter 决定使用云端模型 | `model_name`、`token_estimate`、`cost_estimate`、`reason` | 单次会话 | 否 |
| `sandbox_downgrade` | CubeSandbox → Docker → Native 降级 | `from_mode`、`to_mode`、`reason` | 单次会话 | 否 |
| `native_risk_prompt` | Native 模式风险提示 | `skill_id`、`risk_level`、`reason` | 单次会话 | 否 |
| `plugin_high_risk_skill` | Plugin 调用高危 Skill | `plugin_id`、`skill_id`、`risk_level`、`reason` | 单次会话 | 否 |
| `tool_external_enable` | 显式启用 external Tool | `tool_name`、`scope`、`reason` | 单次会话 | 否 |
| `agent_toolbox_high_risk` | agent-toolbox 高危接口调用 | `caller_skill_id`、`operation`、`reason` | 单次会话 | 否 |

**说明**：所有 Consent 条目均记录 `created_at`、`trace_id`、`actor`，统一一次性审计，不做跨会话复用。

#### 降级路径矩阵

| 场景 | 触发条件 | 降级行为 | 恢复条件 | Consent |
|------|----------|----------|----------|---------|
| CubeSandbox → Docker | CubeSandbox 不可用/安装失败 | 自动切换 Docker 并提示隔离变化 | CubeSandbox 恢复可用 | 是 |
| Docker → Native | Docker 不可用/受限环境 | 切换 Native 并提示风险 | Docker 恢复可用 | 是 |
| 云端路由回退本地 | 云端调用超时/失败 | 回退本地模型兜底 | 云端恢复可用 | 是 |
| IdleThink 降级 | 内存/显存低于阈值 | 降级到规则引擎 | 资源恢复 | 否 |
| 资源紧张暂停 | 可用内存 < 阈值 | 暂停低优先级后台任务 | 资源恢复 | 否 |
| 沙箱退出 | 高危能力缺少权限 | 直接拒绝并提示 | 用户补权限/切换模式 | 是 |

#### UI 规范

- 统一使用樱花粉 Codex 卡片样式。
- Native 模式风险提示使用全橙色边框 + 醒目风险条 + 手动勾选确认 + 二次确认按钮。
- 设置页常驻隔离级别标识：CubeSandbox 绿色「硬件隔离」/ Docker 蓝色「进程隔离」/ Native 橙色「无隔离」。

### 6.4 B 层 陪伴核心

#### 6.4.1 B1 人格会话与上下文压缩（S8+）

- 负责人格装配、prompt 组装，是陪伴人设的核心载体。
- **上下文压缩**：token 超窗口 80% 触发，异步压缩至 60%；保留人设铁律 + 近 N 轮原文 + 本轮召回记忆块。
- 压缩摘要入库 `memory_chunks`，`memory_type=context_summary`，用户可删除。

#### 6.4.2 B2 记忆

| 项 | 共识 | 状态 |
|----|------|------|
| 唯一写入闸门 | 仅 `#remember` 触发写入；压缩摘要可删除 | ✅ 闸门 |
| `memory_type` | `fact` / `habit` / `preference` / `context_summary` / `goal` | 🔲 待做 |
| `status` | `active` / `cancelled`；召回仅返回 active 状态 | 🔲 待做 |
| 习惯取消 | 冲突记忆标 cancelled，不新增条目 | 🔲 待做 |
| 时间戳 | `memory_chunks`、`messages` 均带 `created_at` | 🔶 部分完成 |
| 衰减机制 | 时间越近权重越高；远期降权不归零 | ✅ |
| 压缩摘要 | `fidelity`、`round_range`、`compression_batch` 字段 | 🔲 待做 |
| 压缩原则 | 基于原始对话；不二次压缩；按轮次区间 | 🔲 待做 |
| 召回优先级 | 用户事实 > Agent 人设 > 会话历史 | ✅ |
| 混合检索 | 向量语义 + BM25 + FTS5 三路召回融合排序，附带引用标记 | 📅 S9A |
| 冷热分离 | 热数据常驻快速索引，冷数据归档磁盘，可配置阈值 | 📅 S9+ |
| 基础骨架 | `#remember` 闸门 + FTS / 衰减 / 可编辑召回 | 🔶 部分完成 |

#### 6.4.3 B3 安全模块

- 系统硬边界，负责内容安全检测；配置位于 `configs/safety_replies/`，用户不可修改。
- 命中违规内容直接阻断，返回固定安全话术。
- 检测规则与关键词库复用到 AutoRouter 隐私敏感度判定、GoalManager 负反馈判定。

#### 6.4.4 B4 输出润色闸门

- 所有输出的最后闸门，负责人格润色、格式校验、内容安全二次校验。
- Skill 声明 `output_mode: "raw"` 时，仅做格式安全检测，不注入人格润色。
- 云端模型返回结果必须经过 B4 校验后才能返回给用户，不得绕过。

### 6.5 C 层 算力与存储

#### 6.5.1 C1 推理层

- 抽象 LLMBackend 接口，当前实现 LlamaCppBackend，基于 llama-cpp-python + GGUF。
- 默认模型：Qwen2.5-1.5B-Instruct Q4_K_M。

#### 6.5.2 C2 存储层

- 抽象 VectorStore 接口，当前实现 SqliteVecStore。
- 向量写入先落 SQLite vector_queue 表 WAL 日志，后台异步更新索引；WAL 写入后立即 fsync 落盘。
- 启动时先同步重放 WAL 未索引数据，重放完成前不提供召回服务。
- 主数据 + 向量索引双写，写入成功以 SQLite 主库为准；召回时合并查询，按 ID 自动去重。
- 每小时校验主数据与向量索引条数，不一致自动增量修复；提供 reindex 命令重建全量向量。
- 性能基线：10 万条记忆下召回延迟 < 50ms。

### 6.6 Plugin 安全隔离（S8）

| 项 | 共识 | 状态 |
|----|------|------|
| iframe 沙箱隔离 | 每个 Plugin 运行在独立 iframe，禁止访问主页面 DOM，仅通过 postMessage 与 Bridge 通信 | 📅 S8 |
| Bridge 签名校验 | 每个 Plugin 分配独立令牌，校验权限范围；参数做严格类型 + 值域校验 | 📅 S8 |
| 上架安全扫描 | 检测危险 API、XSS payload、越权调用尝试，不通过禁止上架 | 📅 S8 |
| iframe sandbox 最小化 | 默认仅 `allow-scripts`，按需开启其他属性 | 📅 S8 |
| 存储完全隔离 | 每个 Plugin 的 localStorage、cookie、IndexedDB 完全独立 | 📅 S8 |
| Skill 调用白名单 | Plugin 可调用的 Skill 必须在 plugin.json 声明，未声明直接拦截；高危调用走 A3 Consent | 📅 S8 |

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

---

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
5. **agent-toolbox 外骨骼**：所有「行动」经独立 CubeSandbox/Docker 沙箱 Skill 执行，不污染核心进程；A3 Consent 为每步操作提供可审计闸门。
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
| CubeSandbox 稳定性待验证 | 自动降级 Docker/Native + Consent 提示；CubeSandbox 不可用时不影响核心功能 | 中 | S7.7 |
| Docker 强制依赖摩擦 | CubeSandbox/Docker/Native 三级降级 + Consent 提示 | 中 | S8 |
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
| Plugin 扩展点不足 | S8 同步实现 sidebar_panel / message_bubble / settings_section | 中 | S8 |
| 章节编号与状态标记混乱 | 全局枚举 + 重排编号 | 低 | 本次合并 |
| 非功能需求缺失 | 补充性能/稳定性/资源占用基线 | 低 | S8 |
| 测试体系无顶层设计 | 分层测试策略 + CI 流水线 | 低 | S8 |
| Native 模式安全依赖声明式约束而非进程级强制 | 文档明确标注隔离强度差异；高风险 Skill 推荐仅 Docker 模式 | 低 | S8 |
| 缺少零代码定制能力 | 助理模板 + 人设可视化编辑 + 提醒规则配置面板 | 中 | S9 |
| 跨端能力缺失 | 局域网 WebUI 接入（数据全在本地）→ 端到端加密多端同步 | 低 | S10+ |
| 模组开发门槛偏高 | 低代码脚手架 + 商城配套创作者工具 | 低 | S10+ |
| 模型路由依赖静态规则，缺乏个性化 | AutoRouter + 用户反馈学习（S10+） | 中 | S10+ |

---

## 十一、Sprint 边界

### 已闭合

Sprint 0～6.8；**7.1 ✅** `skill_manager` registry/policy + 收尾（`extensions/installed/`、`type` 分流、CSP / 错误码占位）。

### Sprint 7（当前）

**安全地基闭合（Sprint 7 只做安全地基，其余全部后移）**：

| 子项 | 内容 | 状态 |
|------|------|------|
| 7.1 | registry/policy + extensions/installed/ + type 分流 | 🔶 部分完成 |
| 7.2 | Consent `purpose_type` + API Key 宿主注入 + Skill API 鉴权（随机 Key + 动态端口） | 🔲 待做 |
| 7.8 | **运行时网络沙箱**（B/C 层 socket/urllib 替换 + 禁用 exec/eval/importlib） | 🔲 待做 |

**收尾条件**：7.2 + 7.8 全部完成后，Sprint 7 安全地基即视为闭合 ✅。

**Sprint 7 核心交付（必做）**：
- 前置规则过滤器 + 短路路由
- risk_level 自动判定 + 高风险默认 Docker
- C1/C2 接口抽象 + API 版本前缀 + 响应格式标准化
- 分层依赖检查脚本 + pytest 门禁脚本（CI 最小骨架）
- **已落地并可视为 Sprint 7 基础完成的能力**：
  - `StateManager` 基础三域封装（session / task / system 统一读写 API）
  - `BaseMessage` 基础协议 + 同步版 `MessageRouter` 最小路由骨架
  - `runtime_sandbox` 运行时危险能力最小兜底
  - `SkillInvoker` 基础熔断（连续失败计数 + 熔断拦截）
  - `check_imports` AST 分层门禁 + 直接执行入口修复
  - 跨平台路径 / 编码 / 测试 fixture 兼容修复

**Sprint 7 收尾补充**：
- `runtime_sandbox` 更完整白名单与子进程级兜底（TODO 保留）
- `SkillInvoker` 半开探测与恢复窗口（TODO 保留）
- `check_imports` 更细粒度白名单与测试覆盖（TODO 保留）
- `check_imports` 基础门禁 + 运行时沙箱 + pytest 组合已纳入 CI 门禁
- `CubeSandbox` 仅保留可行性验证，不进入 Sprint 7 主交付

**可选交付（不阻塞安全地基闭合）**：
- **CubeSandbox 可行性验证**（Sprint 7 第一周可启动，但不阻塞核心交付）：只测三个核心指标——跨平台启动速度、内存占用、基础逃逸测试。验证不通过，直接降级为远期规划，所有 CubeSandbox 特性从主文档移入附录，后续不再投入核心资源。
- 响应格式全量对齐

**缓冲机制**：每个 Sprint 功能点排期最多占 70% 工时，预留 30% 用于跨平台踩坑、联调、Bug 修复。所有依赖第三方项目的功能，先做一周可行性验证，通过再排入正式迭代。

**后移项（Sprint 8 起）**：skill-market 独立仓 MVP API、novel-writer 独立 Skill、`/skill` CLI、评测扩展、agent-toolbox MVP、错误码校验逻辑落地 + 基础熔断。

### Sprint 8

**第一批（安全与稳定性，优先）**：
- **Plugin 安全隔离**（Shadow DOM + Bridge 白名单 + 权限校验）
- **JobScheduler**（核心调度 + 持久化 + 心跳 + Skill 存活检查）
- **向量读写一致性修复**（检索时同时查 WAL 未索引队列）
- **ErrorCode Schema 完善**（补充 E_DOCKER_UNAVAILABLE 等）
- **venv 隔离 + Native 模式降级**
- **空闲回收 + 白名单 + 单实例复用 + 并发上限**
- **Skill 依赖安全**：依赖哈希校验 + SBOM 自动生成
- **Native 模式系统调用级拦截**：Linux seccomp-bpf 优先，macOS/Windows 后续
- **内置 Skill 文件哈希校验**：启动前完整性校验
- **消息总线工程约定拆解**：ZeroMQ、双队列、幂等、死信队列、会话级串行

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

**AutoRouter**（TaskProfiler 规则引擎版 + CostPredictor + 决策引擎 + 云端路由 Consent；初期对接前置规则过滤器，S9B 对接 Router LLM）；Tool（`tool_registry` + 分级）；**PlanOrchestrator + TaskContext**；**PlanNotebook**；**消息队列升级**（agent-toolbox ZeroMQ/nanomsg 通信模式 + A2 MessageRouter）；**ResourceArbitrator**；**A 层语义封装 + CI prompt 关键词扫描**（Skill 能力描述生成、反向相似度校验、B 层 prompt 解耦、B 层模板关键词扫描、Skill 新增解耦集成测试）；**记忆三路混合检索**（向量语义 + BM25 + FTS5 融合排序、引用标记、召回去重）；**Tool 迁移收口**：S9 收尾前完成所有 external Tool → 微型 Skill 迁移，届时移除 external 入口。

> 9A 目标：先跑通复杂任务编排骨架，确保 PlanOrchestrator 能正确分解、执行和恢复任务。同步完成 Tool 后门封堵。

**Sprint 9 补充**：
- **StateManager + 事件驱动 + 中间件 + 单职责字段**

### Sprint 9B（软能力）

**GoalManager + IdleThink 循环**（被动画像的前置）；**AttentionAwareness**；**Router LLM + Self-Reflection**；桌面二次元小人；**UI 微交互**（呼吸灯 + 执行动画 + 待机姿态，与二次元小人并列）。

**Sprint 9B 补充**：
- **场景静默 + 频率硬锁 + 负反馈硬降权 + 语义负反馈 + 紧急仅用户标记 + B4 闸门 + 默认关闭渐进解锁**

| 子项 | 内容 | 状态 |
|------|------|------|
| 助理模板 | 4 套预设模板（高效办公 / 生活管家 / 学习陪伴 / 情绪陪伴），首次启动引导式选择 | 🔲 待做 |
| 人设可视化编辑 | 设置中通过表单修改人设，实时生效 | 🔲 待做 |

> 9B 目标：在 9A 骨架跑通后，叠加主动关心和注意力感知等软能力，降低调试复杂度。

### Sprint 10+（远期探索）

- **AutoRouter 升级**：TaskProfiler 升级微型 LLM；引入用户反馈学习 + ResourceArbitrator 资源状态反馈，实现个性化路由；**成本预估模型自优化**（根据实际消耗回传数据持续校准预估准确率）
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
| 硬件检测 | 下载器/安装器内置；检测 GPU 显存、系统内存、可用磁盘 |
| 向量扩展 | sqlite-vec |
| 消息总线 | ZeroMQ / nanomsg（后台任务链路）+ 同步函数调用（主对话链路） |
| 依赖隔离 | venv（每个 Skill 独立 `.venv/`） |
| 系统调用拦截 | Linux seccomp-bpf / macOS sandbox-exec / Windows Job Object |
| SBOM | `extensions/installed/<skill-name>/sbom.json` |
| 向量性能基线 | 10 万条记忆召回延迟 < 50ms（含未索引队列合并开销） |
| 推理接口抽象 | C1 推理抽象为 LLMBackend 接口，当前实现 LlamaCppBackend |
| 存储接口抽象 | C2 向量存储抽象为 VectorStore 接口，当前实现 SqliteVecStore |
| API 版本前缀 | 所有 HTTP 接口统一使用 /api/v1/ 前缀 |
| 响应格式标准化 | Skill 请求/响应统一封装为 {code, data, error} 结构 |
| **Skill 沙箱** | Docker（核心底座，进程级隔离）/ CubeSandbox（可选增强，实验性）/ Native（仅限官方内置 Skill） |
| **CubeSandbox 单实例内存** | <5MB（实验值） |
| **CubeSandbox 启动速度** | <60ms（实验值） |
| **CubeSandbox 并发上限** | 20 个实例（实验值；Docker 模式 3 个，Native 模式 1 个） |
| **模型路由配置** | `configs/model_routing.yaml`（成本、延迟、能力标签、阈值） |
| **能力标签枚举** | `shared/` 层统一定义（`chat`、`code_generation`、`complex_reasoning`、`tool_use`、`simple_qa`） |

**不引入**：torch、langchain、chromadb、faiss、Electron、npm 构建链（Plugin 亦零构建）。

```
{data_root}/
├── companion.db
├── knowledge.db              # 内置知识 RAG
├── configs/
├── models/
├── extensions/installed/     # 目标路径（模组统一目录）
│   ├── <skill-name>/
│   │   ├── manifest.json
│   │   ├── sbom.json
│   │   └── .venv/
│   ├── <plugin-name>/
│   │   └── plugin.json
│   └── <tool-name>/
│       └── manifest.json
├── exports/
├── dead_letter_queue/         # 死信队列持久化位置（逻辑目录）
└── logs/
```

运维命令见 [`USER_MANUAL`](./USER_MANUAL_v1.0_zh.md)。

---

## 十三、文档体系

| 文档 | 读者 | 约束 |
|------|------|------|
| **ARCHITECTURE v2.3** | 开发者/架构师 | **冲突时以本文为准** |
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
| 向量召回延迟 | < 50ms（10 万条，含未索引队列合并开销） | `sqlite-vec` 查询计时 |
| Skill 首次启动延迟 | < 3s（含 venv 激活） | invoker 启动计时 |
| 连续运行 24h 内存占用 | < 2GB（含 1 个本地模型） | 系统监控 |
| Skill 调用成功率 | > 99%（不含用户主动停止） | JobScheduler 统计 |
| 熔断触发误判率 | < 1% | invoker 日志统计 |
| IdleThink 侵扰投诉率 | < 5%（用户关闭功能视为投诉）；用户关闭提醒视为负反馈信号，GoalManager 自动降低该类型提醒权重 | Auto-Eval 统计 |

---

## 十六、测试体系

| 层级 | 范围 | 工具 | 频率 | 准入标准 | 准出标准 |
|------|------|------|------|----------|----------|
| **单元测试** | 所有模块核心函数 | `pytest` | 每次 commit | 核心模块行覆盖率 ≥80% | 全量 pytest 通过 |
| **集成测试** | A/B/C 层间调用链 + Skill 通信 | `pytest` + fixture | 每次 PR | 覆盖所有 A/B/C 跨层调用链路 | 全量通过，无跳过 |
| **端到端测试** | 完整对话流 + Consent 流程 | `full_acceptance.py` | 每 Sprint 收尾 | — | 全量通过 |
| **安全扫描** | AST 静态扫描 + 运行时沙箱逃逸测试 + 依赖漏洞扫描 | CI 门禁 | 每次 PR | 三项全启动 | 三项全通过，任一不通过 CI 阻断 |
| **性能基准** | 非功能需求基线各项指标 | 独立脚本 | 每 Sprint 收尾 | — | 所有指标达标 |
| **降级路径测试** | 沙箱降级、熔断触发、资源紧张、网络异常 | 降级场景测试清单 | Sprint 8 起每 Sprint | 每种场景有标准化测试脚本 | 每次 PR 自动跑 |

**CI 门禁规则**：
- **分层依赖检查**：禁止 B 调 A、C 调 B 的 import，违反则 CI 不通过
- **安全扫描**：`check_imports` + AST 扫描 + 运行时沙箱 + 依赖漏洞扫描，违反则 CI 不通过
- **单元测试**：设为强制门禁，不通过不准合入
- **check_imports 增强**：基础门禁 + 运行时 socket/urllib 全局替换为异常类 + 禁用 exec/eval/importlib 动态导入
- 以上规则在每次 PR 时自动执行，不满足任一条件则阻断合入

**Sprint 7 收尾前**：完成 CI 最小骨架搭建——分层依赖检查脚本 + pytest 门禁脚本，不要求全覆盖，但骨架必须跑通。Sprint 8 起逐步扩展覆盖率。

- **无测试不合并**：功能 PR 必须附带对应测试用例，没有测试用例的 PR 直接打回，不准先上线后补测试。

---

## 本次修订说明

本次修订严格针对前版指出的所有致命问题做了根治，核心修改点如下：

### 1. 结构与编号重构（致命问题修复）

- 彻底重排第六章结构，严格按照 **A1 → A2 → A3 → B 层 → C 层 → Plugin** 的分层顺序组织，层级编号连续无重复、无跳号、无乱插，彻底解决了编号崩盘、逻辑混乱的问题。
- 移除了重复 4 次的三大模块定义，每个模块仅保留**唯一正式定义**，状态、约束、排期统一在一处，消除了多口径冲突，恢复了单一真值源。
- 移除了所有混入正文的评审式内容（优点、缺点、优化建议），恢复架构文档「定义规范、明确约束」的权威属性，过程性评审内容不再混入正式基准。

### 2. 架构逻辑矛盾修复

- **主链路顺序修正**：明确 PlanOrchestrator 在 invoker 上游，负责调度多步骤 Skill 执行，解决了此前链路顺序颠倒的硬错误。
- **模块边界厘清**：
  - StateManager 剥离业务逻辑，明确仅负责状态存储与事件分发，空闲检测归 A1，修正了职责越界问题。
  - 明确 Policy 做全局策略校验、Router LLM 做意图路由、AutoRouter 做模型路由，三者职责完全拆分，解决了职责重叠、后续必然冲突的隐患。
- **错误码分层修正**：将策略类错误（E_POLICY_DENIED、E_CONSENT_REQUIRED 等）的 source 从 B3 修正为 A2，B3 仅负责内容安全错误，完全符合分层定义。

### 3. 规范与口径统一

- 全文档状态标记严格使用 ✅ / 🔲 / 🔶 / 📅 四类标准枚举，移除了所有纯文字「待做」「部分」等非标准标注，遵守了文档自定的规则。
- 所有排期与 Sprint 边界章节严格对应，消除了同一功能标不同 Sprint 的矛盾。
- 统一所有模块的描述结构：先定位 → 核心能力 → 关键约束 → 状态表，可读性与一致性大幅提升。

### 4. 内容完整性保留

- 所有原架构共识、安全约束、功能规划、排期计划全部保留，未做任何实质删减。
