# 文档变更记录（CHANGELOG）

本文件记录 **`docs/` 目录** 的版本与结构变更，不替代 Git 提交历史。

---

## v1.7.0 · 2026-08-22（任务拆解可靠性增强）

### 设计与实现
- 手动计划改为以 `TaskContext` 快照作为唯一事实源，旧计划表降为桌面 API/UI 兼容投影。
- 新增任务拆解样本库 S1 骨架，复用 `memory_chunks` 保存候选样本，并建立用户主权生命周期状态机与事件留痕。
- 完成任务拆解样本库 S2：本地 verified 样本混合检索、few-shot 安全裁剪注入、动态开关、候选全量留档与计划 provenance 接线。
- 收敛 `decomp_learning_enabled` 语义：关闭时只停用检索和注入，LLM 与规则拆解仍持续留档 candidate。
- 完成任务拆解样本库 S3：计划终态回写 provenance 使用统计，全绿 candidate 自动验证，连续失败样本自动 stale，并隔离反馈链异常。
- 完成任务拆解样本库 S4：新增本地 CRUD API、状态筛选与详情编辑页面、stale 复核提示，以及终态计划“查看/存为范例”入口；前端操作采用乐观更新与失败回滚。
- 完成任务拆解样本库 S5：修复属性上下文转义，状态筛选与分页下沉 SQLite，新增 exact/近重复原子合并与 provenance 归因转移，并由 IdleThink 每日执行容量治理和冷归档。
- 收敛 Plan Mode 幻觉防护：讲解意图优先于任务短语，移除连接词式误判；规则 fallback 仅保留代码、部署、分析三类专用模板，无领域匹配时直接降级普通对话。
- 修复手动 Plan 终态正文链：覆盖“能详细讲讲吗”类对话意图，终态回复渲染后再次滚动到底部，并将手动计划的用户输入与幂等终态正文写入消息历史；同步更新静态资源版本避免旧脚本缓存。
- 修复 Windows 桌面单实例 PID 探活：使用 `OpenProcess` 替代不兼容的 `os.kill(pid, 0)`，避免 stale PID 清理阶段触发 WinError 87 / SystemError 并阻断启动。
- 新增会话算术断言审计：以 NFKC、显式断言提取和 `Decimal` 双轨比较识别错误计算，复用一次质量重试并在失败时追加确定性警示；同步覆盖流式终态替换以及手动/Auto 计划统一 `final_reply`。
- 扩展算术断言系动词形态，覆盖“3乘7的结果是14”与“3乘7是14”，并以不含回复原文的 debug 计数记录提取、失败和重试审计结果。
- 新增拆解保真 B4：算法、协议、格式约束丢失时定向重拆一次，仍失败则在手动与 Auto 链明示能力边界并降级本地对话；同时拦截低风险单步复述型零增值计划，不创建候选样本。
- 补齐无云默认链路验收与决策观测：约束拒拆后继续使用本地回复和算术审计，不要求或提示配置云端；拆解日志记录入口门控、来源、步骤数、相关性、约束重试与最终裁决。
- 新增首个确定性算法工具 `algorithm_booth`：Booth 方法请求绕过 LLM 拆解，执行本地算法并输出重编码、部分积与寄存器中间态，再交由 LLM 转述，结果继续通过算术审计。
- 新增本地确定性 `calculator` 工具：基础四则与整数幂支持阿拉伯及中文数字输入，算术请求绕过 LLM 数值推理并复用统一审计。
- 新增 B4 GBNF 实验 harness：固定 20 个工具选择样本、生成 `none` 分支文法并输出可审计的完成率；未连接本地 sidecar 时明确报告 blocked，不伪造实验结果。
- 修复确定性工具计划执行：builtin 工具不再误写入样本库，calculator 结果在计划快照中保持 JSON 可序列化。
- 扩展方法约束双通道识别：算法专名（如 `booth`）可直接触发确定性工具，不再要求后缀必须出现“算法”。
- 补齐拆解链路可观测性：算术审计 info 日志记录提取数、失败数与跳过原因；拆解决策日志记录 R3/B3/B4 命中详情；LLM 拆解原始输出保留 debug 全文并输出可检索元数据。
- 完成 Batch C Booth GBNF 实验判决：托管 sidecar pre-flight 确认 grammar 生效，20 个不同乘法对全量完成；`full_success_rate=0.0`，plan-as-reasoning 关闭入档，确定性算法继续走工具化路径。
- 完成 Batch D-1 词典-工具同源收口：`ToolManifest` 新增 `algorithm_names` 与 `trigger_keywords` 分字段声明，B4 算法专名词典启动期从 `ToolRegistry` 可用工具并集注入，避免拆解器手写词表与工具集漂移；历史硬编码中的 `utf-8`/`utf8` 从算法专名通道移除，保留“编码/格式”类别通道。
- 完成 Batch D-2 工具扩容：新增 `algorithm_crc32`、`algorithm_gcd`、`algorithm_quicksort` 三个本地确定性算法 Tool；CRC-32 在工具本体内执行按位迭代并与 `zlib.crc32` 交叉验证，欧几里得返回余数序列，快速排序返回 Lomuto 分区快照；拆解器按 manifest 映射消费 `trigger_keywords`，裸“最大公约数”和大写 `CRC` 输入可直接路由工具。
- Batch D-2 验证基线：`pytest -q` 为 1071 passed、3 skipped；`scripts/full_acceptance.py --skip-gpu` 全部 10/10 通过。
- 完成 Batch D-3 降级链与边界补账：CRC-32 输入在工具本体拒绝超过 64 个 UTF-8 字节且不截断，新增 `123456789 -> 0xCBF43926` 标准 check 值；欧几里得锁定 `gcd(0,n)=n`、`gcd(0,0)=0` 与负数绝对值语义；词典外 `MD5` 算法请求进入可见降级链；五判例 drill 路由、执行、转述计划三层全绿。
- 补齐 Tool 事件层：`ToolInvoker` 执行时写入 `tool/call` 与 `tool/result`，payload 保留 `tool_id`、`session_id`、状态与可辨识参数，用于 Batch E 红队前置 drill 定位工具链路。
- 同步 v6 边界战役收尾与主线回归承接计划，并新增 `scripts/drill_algorithm_tools.py`，将 D-3 五判例 route/execute/transcribe drill 固化为可重跑脚本。
- 同步 Batch E 红队开工方案，并记录 E-1 预注册侦察矩阵：15 条主判例当前 `correct=6`、`degraded-explicit=3`、`silent-fail=6`，为 E-2 silent 清零提供对拍基线。
- 落地 Batch E-2a 可见性修复：B4 类别约束补“编码”，工具集内方法缺参返回可见缺参提示，复合算法指令保留首段执行并在转述步骤明示后续片段需分步提交；矩阵重跑从 `6/3/6` 推进到 `6/6/3`。
- 落地 Batch E-2b 正确性修复：整数解析支持 `负三`、`负3`、`−3` 三类负号，快速排序接受空数组边界，算术审计系动词族补 `为`；矩阵重跑达到 `9/6/0`。
- 开始 v6 主线 6.1 回归：W22 基线改为 `1099 passed / 3 skipped` 不退步，确认生产 embedding 为 deterministic hash-bow 768 维近似；语义事件存储新增 768 维 fail-fast、同 ID 冲突传播和 vector_search/extractor 固定日志 anchor。
- 已知债务：`PlanDecomposer` 的 `method_entity_names` / manifest 映射参数仍允许空值以兼容测试与冷路径构造；生产 bootstrap 已传入 callable，后续可将生产装配路径升级为缺失即 fail-fast。

## v1.6.1 · 2026-08-20（Windows 窗口适配修复）

### 修复
- Windows 无边框窗口改用 Per-Monitor DPI 感知与物理工作区定位，修复 125%/150% 缩放下最大化超屏、遮挡任务栏和还原偏移。
- 最大化按当前显示器工作区执行，恢复时对已移除显示器上的旧尺寸和坐标进行夹取，并保留 HWND 获取失败降级。
- 扩大四边与四角缩放热区，使用 Pointer Capture 保持拖动事件，修复缩小状态下无法拖动窗口边缘。
- 桌面布局统一为 compact、standard、wide 三档，并将记忆默认日期范围设为本地今天至一年前同日。

### 验证
- 150% DPI 实机验证最大化与还原均为 0px 误差；窗口控制窄测、JavaScript 语法和 Ruff 全绿。

## v1.6.0 · 2026-08-19（语义记忆与可靠性增强）

### Phase 6 情感语义记忆
- 新增语义事件提取、SQLite 存储、结构化召回、衰减与闲时维护链路，记忆保持可解释、可管理和本地优先。
- 完成 settings v2 分类迁移、模块化 API 与前端统一刷新，兼容旧版扁平配置。
- 修复引导跳过、窗口最大化、思考中断、SSE 历史重放及 Windows JSON 备份排序问题。

### 验收
- v1.6 发布前全量测试：817 passed、3 skipped；Ruff 全绿。
- Windows 安装器仅包含程序核心；本地模型由首次引导按用户选择下载，不再随安装包捆绑。

### Phase 5 可观测性与 UI 自动化
- 新增 trace/Trajectory、健康检查、诊断报告、覆盖率门禁和性能基准能力。
- 新增 UI 标注会话、`ui_map.yaml` / `manifest.json` 私人 Skill 导出、PageLocator、PageIdentifier 和可注入式 UI 操作安全执行器。
- UI 自动化支持序列级 Consent、hard danger 二次确认、中断 fail-closed 和 `ui/action_executed` 审计事件；真实桌面 Actor 与 PluginFiber provider 接线仍按技术债跟踪。

### Phase 4 插件架构
- 统一扩展生命周期：`PluginFiber` 状态机、`EffectScope` 资源托管、声明式 YAML 拓扑加载和确定性卸载。
- 新增 `ProviderRegistry` 与 `ModelProvider` 抽象；请求开始捕获 Provider 快照，支持 HMR 且不影响在途请求。
- 新增 Monotonic Guard 与 fail-closed 默认策略；Consent 审计强制 `asked` + `decided` 配对。

### 设计
- 新增《UI 自动化操作引擎技术方案》，冻结零代码标注、Skill 包格式、A 层宿主 broker、目标窗口硬锁、序列级 Consent、OCR 定位缓存与私人分发边界。
- 新增《1.5B 模型 Function Calling 方案》，定义双本地后端 GBNF 约束、A2 工具选择与执行前参数校验、单步单工具和可观测性边界。

### 修复
- 本地 GGUF 默认目录统一为程序根目录相对路径 `models/`；开发模式使用仓库 `models/`，冻结版使用可执行文件旁的 `models/`，后续模型下载沿用同一路径。

### Phase 3 模型下载与首次引导
- 新增 A 层模型下载器：断点续传、多源回退、SHA256 校验、取消、进度 API/SSE 和下载生命周期审计。
- 新增首次启动三步引导；模型下载完成后自动激活本地 backend 并同步 AutoRouter，加载失败沿用 Phase 1 降级链。
- 安全模型明确下载器属于 A 层并受 A2 许可；模型文件缺失、损坏或校验失败时提示重新下载，不静默上云。

### 新增能力
- Superpowers Prompt Skill 支持声明阶段序列；新增 SQLite `skill_executions` 状态跟踪、`HardGate` 前置检查和宿主注入会话 ID 的本地 `skill_advance_stage` 元工具。

### Phase 2 事件流
- 新增全局 append-only `DomainEvent` 事件流、SQLite 持久化与启动恢复，按 `(stream_id, seq)` 保证顺序和幂等。
- SSE 断连支持 seq gap repair；Projection 提供开发模式 Trajectory 时间线，事件以 `trace_id` 串联一次 turn。
- Consent 事件补齐 `consent/asked` + `consent/decided` 审计对；模型切换、降级和不可用状态记录 `model/switched`、`model/degraded`、`model/unavailable`。

---

## v1.3.0-alpha2 · 2026-08-15（Phase 1 可靠性加固）

### 可靠性
- 本地模型 sidecar 启动边界收紧为 30 秒，统一处理进程创建失败、提前退出与健康检查超时；桌面启动按隐私模式进入 `cloud_fallback` 或 `no_backend`，不再因本地模型加载失败崩溃。
- SSE 对话事件与 partial 消息持久化，断连后可按序号补偿缺失事件，避免中途回复丢失。
- 本地 JSON 状态增加原子写入、三份轮转备份、损坏恢复与启动提示；新增本地崩溃日志、异常退出检测和仅本地查看/归档流程。
- 完成 ThreadPoolExecutor、Timer 与 cron 隐性超时扫描；桌面延时 Timer 统一 daemon 化、登记并在退出时取消。

### 安全与体验
- Consent 拒绝改为正常 `declined` 响应和固定自然语言回复，不返回 403/error、不触发错误 toast；`deny` Artifact 与对话记录继续持久化。
- 本地加载失败时严格保持 LOCAL_ONLY 零出站；ASK 模式仍走 Consent，仅 AUTO_ROUTE_CLOUD 允许自动切云端。

### 验收
- Phase 1 全量测试：671 passed、3 skipped，较 643 基线增加 28 项且无退步。
- 六项集成场景通过：模型缺失降级、SSE 断连恢复、settings 损坏恢复、崩溃启动提示、隐性超时复扫、Consent 拒绝自然反馈。

---

## v1.2.1 · 2026-08-10（模型适配 P1）

### 增强
- 新增五维 `CapabilityProfile`，模型 YAML 支持多维画像并兼容旧单值配置。
- B1 根据模型画像调整 OCEAN 语气指令、记忆召回上限和显式格式约束。
- B4 本地与云端润色链路按角色扮演能力选择最小修正或完整润色。
- 云端模型配置支持持久化能力画像，继续严格掩码 API Key。

### 验收
- 模型适配 P1 三个 Batch 全部闭合：416 passed、3 skipped，Ruff 全绿。

---

## v1.2.0 · 2026-08-10（Sprint 10 Auto Mode）

### 新增能力
- Auto Turn 将规则拆解、per-step LOCAL/CLOUD 路由、单步 DAG 执行与结果组装接入生产聊天入口。
- 新增多步骤 SSE 事件协议和前端计划卡片，实时展示步骤路由、进度、失败与跳过状态。
- Consent 暂停状态与 request_id 持久化到 SQLite，用户决定后可跨请求恢复计划。
- 云端模型凭证通过宿主 provider 注入执行链，不依赖环境变量且不向 DOM 暴露明文 Key。

### 安全与兼容
- Consent request_id 由后端生成并校验，不信任客户端自报授权结果。
- Auto 关闭时普通聊天继续走原 ModelRouter 路径；旧 `/api/plan/decompose` 保留薄代理兼容。
- Auto 开启前要求至少一个已启用云端模型，并与旧 Plan Mode 互斥。

### 验收
- Sprint 10 后端完整回归：405 passed、3 skipped。
- Batch 4 桌面 HTTP 窄测：44 passed；`shell_api.js` 通过 `node --check`。

---

## v1.0.0 · 2026-08-01（首个桌面发布候选）

### 发行基线
- 默认模型保持 `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`，不在 v1.0 升级 7B。
- Windows 桌面链路闭合：PyInstaller 便携包 + `llama-server.exe` sidecar + Inno Setup per-user 安装器。
- 桌面 HTTP 从 Flask dev server 切换为 Waitress WSGI，生产启动不再出现 development server warning。
- 发布体验补齐 favicon、PIL 日志抑制、About 信息、崩溃日志和 HTTP JSON 错误响应。
- 安装器只安装主仓库本体；Skill 仓库与下载器仓库保持独立，不随 v1.0 安装器分发。

### 验收
- 基线：338 passed, 3 skipped；新增发布面测试后基线允许前进，不允许回退。
- P6 干净 Windows VM 与 P7 Inno Setup 安装器已闭合。
- 卸载仅清理安装目录，保留 `%LOCALAPPDATA%\Offline Companion\` 用户数据。

---

## v2.5 · 2026-07-26（Sprint 9A 文档同步）

### 变更
- 中英文架构文档同步到 `v2.5`，日期更新为 2026-07-26。
- 同步 Sprint 9A P0-P4 实际交付进度：模型适配 P0、AutoRouter、PlanOrchestrator / TaskContext v2、三路混合检索、A 层语义封装与 CI prompt 解耦约束已闭合。
- 英文架构文档文件名更新为 `ARCHITECTURE_v2.5_en.md`，并同步消息总线状态、JobScheduler 状态、模型路由与检索实现边界。

---

## v2.4.2 · 2026-07-26（Sprint 8 文档同步）

### 变更
- 中英文架构文档统一同步到 `v2.4.2`，日期更新为 2026-07-26。
- 同步 Sprint 8 实际交付进度：地基修复、B0 情绪链路、安全底座、消息总线与调度能力已闭合。
- 英文架构文档文件名更新为 `ARCHITECTURE_v2.4.2_en.md`，并同步 A 层语义封装、CI prompt 解耦扫描、manifest 关键词目录等约束。

---

## v2.3 · 2026-06-30（安全闭环修订 · 架构约束收紧）

### 破坏性变更
- Native模式收紧：Windows/macOS下第三方Skill禁止使用Native模式，仅允许官方签名内置Skill运行；本地手动加载Skill执行同等权限规则，调试模式单独开关
- 熔断规则变更：熔断计数仅统计服务端错误，参数非法、权限不足等客户端错误不再计入，半开探测改用健康检查请求，不再使用用户业务流量
- StateManager隔离升级：状态按域拆分，跨域读写API直接抛异常；模块间禁止直接函数调用，必须通过消息总线通信

### 架构调整
- 消息总线明确协议与实现分离：核心对话链路同步执行，后台任务链路异步执行；同一会话双队列物理隔离，主对话优先级高于后台任务
- A2层控制面/数据面拆分落地：明确模块职责边界，状态读写统一走StateManager API，新增模块域隔离与调用链CI扫描规则
- A层语义封装补充校验机制：新增CI prompt关键词扫描、解耦集成测试，确保B层不感知Skill实现细节
- PlanOrchestrator能力分层：快照回滚明确为CubeSandbox专属增强功能，基础模式依赖TaskContext+幂等步骤实现容错，不绑定实验性沙箱

### 安全加固
- agent-toolbox权限闭环：自身权限最小化，高危权限默认关闭需单独Consent；不同Skill调用分配独立沙箱实例，禁止共享运行时环境；宿主代理二次鉴权，防止权限穿透
- Plugin安全体系补全：iframe sandbox最小化配置、存储完全隔离、Skill调用白名单约束，封堵前端侧权限绕过路径
- 记忆一致性兜底：WAL启动同步重放、内存队列原子操作、召回结果自动去重，修复异步向量写入的数据一致性隐患
- 前置过滤器规则修正：取消纯字数阈值判断，改用关键词+意图规则，明确漏判率<0.1%验收标准，短路链路支持自动回退

### 工程规范
- 测试体系新增铁律：无测试用例的PR禁止合并；CI门禁补充AST扫描、分层依赖检查、沙箱逃逸标准用例
- Sprint排期规则优化：核心交付与可选交付拆分，第三方功能先做可行性验证再排入迭代，每个迭代强制预留30%缓冲
- 文档规范统一：状态标记枚举标准化，CubeSandbox所有性能指标明确标注为实验值，不与Docker正式基线混用

### 规划对齐（待落地，对应Sprint 8–9）
- S8：Plugin安全隔离、JobScheduler核心能力、错误码体系完善、venv隔离与空闲回收机制
- S9：StateManager全量落地、PlanOrchestrator骨架、GoalManager+IdleThink主动能力、Router LLM与Self-Reflection

---


## v2.1.2 · 2026-06-12（Plugin 形态 + 商城约束）


- **PLUGIN_DEV_GUIDE**：`plugin.json`、目录结构、`permissions`、生命周期、商城与本地加载对齐
- **ARCHITECTURE §三–§四**：清单文件名分流；商城 UI/安全/本地加载约束
- **SKILL_DEV_GUIDE / USER_MANUAL**：Skill `manifest.json` vs Plugin `plugin.json`；商城分类与卡片

代码待 S8：`plugin_loader` 读取 `plugin.json`（见 `_TEMP_NEXT_STEPS` #11）。

---

## v2.1.1 · 2026-06-12（7.1 收尾）

### 代码对齐纪要定稿

| 项 | 变更 |
|----|------|
| 安装目录 | `extensions/installed/`（方案 B，无过渡别名） |
| Schema | 必填 `type`；`skill` 条件必填 entrypoint；可选 `content_security_policy`、`error_codes` |
| registry | `installed_extensions_dir`；`load_installed_manifests` 仅 `type=skill` |
| 测试 | +4 项（type / plugin 拒绝 / CSP 占位 / 分流扫描） |

用户定稿：不抢 7.1 的项保持 Sprint 8/9+ 节奏；知识 RAG 仍为内置能力。

---

## v2.1 · 2026-06-12

### 纪要全面落地

按 **2026-06-12 开发会话** 重写四份核心文档，对齐 Skill / Plugin / Tool 三分、模组商城、语音链路、AgentScope 启示、Sprint 7–9 边界。

| 变更 | 说明 |
|------|------|
| ARCHITECTURE v2.0 | 扩展生态矩阵、内置能力 vs Plugin、模组商城、语音、不足表、Sprint 表 |
| SKILL_DEV_GUIDE | `type:skill`、禁止 UI、CSP/错误码占位、skill-market 独立仓 |
| PLUGIN_DEV_GUIDE | **重写**为 WebView 动态 UI；知识 RAG 迁至 ARCHITECTURE 内置能力 |
| USER_MANUAL | 面向用户；截图占位；减少代码块 |
| architecture_v1.0.md | **恢复**为历史只读基线 |
| _TEMP_NEXT_STEPS_2026-06-12.md | **临时**记录文档/代码冲突与下一步（闭合后删除） |

### 文档与代码差距（7.1 收尾前）

已闭合：安装目录、`type`、CSP/错误码占位。  
仍开放：`plugin_loader`、`tool_registry`、Bridge — 见 [`_TEMP_NEXT_STEPS_2026-06-12.md`](./_TEMP_NEXT_STEPS_2026-06-12.md)。

---

## v2.0 · 2026-06-11

### 结构迁移

废弃四类文档（`architecture-and-roadmap`、`PROJECT_STATUS`、`tech-stack` 等），新建固定十文件结构 + 双语 ARCHITECTURE / SKILL / PLUGIN / USER_MANUAL。

### 内容合并

宪章 + 路线图 + 状态 + 技术栈合并进 v2.0 文档体系；Sprint 7.1 skill_manager 标记完成。

---

## 维护约定

1. 正式文档仅 [`README.md`](./README.md) 所列 + `architecture_v1.0.md`（历史）+ 临时 `_TEMP_*`（须删除）。  
2. 架构/共识 → ARCHITECTURE + CHANGELOG。  
3. 中文权威；英文辅助。
4. 文档版本号与代码 Tag 一一对应，每次发版同步标记对应代码提交。
5. 冲突时 **ARCHITECTURE v2.3 中文** 为准。


