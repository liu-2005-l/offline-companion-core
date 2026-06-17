# 文档变更记录（CHANGELOG）

本文件记录 **`docs/` 目录** 的版本与结构变更，不替代 Git 提交历史。

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
4. 冲突时 **ARCHITECTURE v2.0 中文** 为准。
