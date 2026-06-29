# 文档变更记录（CHANGELOG）

本文件记录 **`docs/` 目录** 的版本与结构变更，不替代 Git 提交历史。

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


