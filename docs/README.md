# Offline Companion 文档导航

> 本目录收录 `docs/` 下的正式文档；结构与版本变更见 [`CHANGELOG.md`](./CHANGELOG.md)。
> **中文架构**：[`ARCHITECTURE_v2.5_zh.md`](./ARCHITECTURE_v2.5_zh.md)
> **English architecture**：[`ARCHITECTURE_v2.5_en.md`](./ARCHITECTURE_v2.5_en.md)
> **历史基线**：[`architecture_v1.0.md`](./architecture_v1.0.md)（只读）

---

## 语言 / Language

| 类型 | 中文 | English |
|------|------|---------|
| **核心架构文档** | [`ARCHITECTURE_v2.5_zh.md`](./ARCHITECTURE_v2.5_zh.md) | [`ARCHITECTURE_v2.5_en.md`](./ARCHITECTURE_v2.5_en.md) |
| **Skill 开发指南** | [`SKILL_DEV_GUIDE_v1.0_zh.md`](./SKILL_DEV_GUIDE_v1.0_zh.md) | [`SKILL_DEV_GUIDE_v1.0_en.md`](./SKILL_DEV_GUIDE_v1.0_en.md) |
| **Plugin 开发指南** | [`PLUGIN_DEV_GUIDE_v1.0_zh.md`](./PLUGIN_DEV_GUIDE_v1.0_zh.md) | [`PLUGIN_DEV_GUIDE_v1.0_en.md`](./PLUGIN_DEV_GUIDE_v1.0_en.md) |
| **用户手册** | [`USER_MANUAL_v1.0_zh.md`](./USER_MANUAL_v1.0_zh.md) | [`USER_MANUAL_v1.0_en.md`](./USER_MANUAL_v1.0_en.md) |
| **Superpowers 集成设计** | [`superpowers-integration-design.md`](./superpowers-integration-design.md) | — |
| **Subagent 基础设施设计** | [`subagent-infrastructure-design.md`](./subagent-infrastructure-design.md) | — |
| **UI 自动化 Skill 生成方案** | [`Skill无门槛生成方案.md`](./Skill无门槛生成方案.md) | — |
| **1.5B Function Calling 方案** | [`FunctionCalling小模型方案.md`](./FunctionCalling小模型方案.md) | — |
| **v1.7.0 收尾清单** | [`v1-7-0-release-checklist.md`](./v1-7-0-release-checklist.md) | — |
| **v1.8.0 收尾清单** | [`v1-8-0-release-checklist.md`](./v1-8-0-release-checklist.md) | — |
| **窗口自适应布局方案** | [`window-adaptive-layout-design.md`](./window-adaptive-layout-design.md) | — |
| **v6 主线回归计划** | [`optimization-plan-2026-08-25.md`](./optimization-plan-2026-08-25.md) | — |
| **v1.8.0 V1 真 embedding 方案** | [`v1-8-0-batch-v1-semantic-embedding-design.md`](./v1-8-0-batch-v1-semantic-embedding-design.md) | — |
| **拟人表述升级设计** | [`oc-persona-expression-upgrade-design.md`](./oc-persona-expression-upgrade-design.md) | — |
| **拟人表述 W1 判据** | [`oc-persona-expression-w1-criteria.md`](./oc-persona-expression-w1-criteria.md) | — |
| **Phase 6.5 召回注入 Fixture** | [`phase6-5-recall-injection-fixtures.md`](./phase6-5-recall-injection-fixtures.md) | — |
| **Batch E 红队方案** | [`red-team-batch-e-design.md`](./red-team-batch-e-design.md) | — |
| **Batch E 红队矩阵** | [`red-team-matrix-2026-08-25.md`](./red-team-matrix-2026-08-25.md) | — |

---

## 使用建议

| 需求 | 入口 |
|------|------|
| 了解整体原则、分层、Sprint 边界、技术路线 | **ARCHITECTURE** |
| 开发本地 Skill、localhost API、manifest | **SKILL_DEV_GUIDE** |
| 开发桌面 UI 插件、`plugin.json`、WebView 能力 | **PLUGIN_DEV_GUIDE** |
| 安装、配置、模型放置、验收与日常使用 | **USER_MANUAL** |
| 查看强任务锚定、HardGate 与 Verification 闭合状态 | **superpowers-integration-design** |
| 查看 Subagent 隔离、受限工具、审查协议与已知债务 | **subagent-infrastructure-design** |
| 查看零代码 UI Skill 标注、宿主自动化与安全边界 | **Skill无门槛生成方案** |
| 查看小模型 GBNF 工具选择、参数校验与降级设计 | **FunctionCalling小模型方案** |

---

## 实验记录

| 文件 | 用途 |
|------|------|
| [`gbnf-booth-experiment-2026-08-24.json`](./gbnf-booth-experiment-2026-08-24.json) | Batch C Booth GBNF 步骤生成实验记录；pre-flight 通过，20/20 完成，`full_success_rate=0.0` |

---

## 临时文档

| 文件 | 用途 |
|------|------|
| [`_TEMP_NEXT_STEPS_2026-06-12.md`](./_TEMP_NEXT_STEPS_2026-06-12.md) | 临时代办与阶段性缺口记录，后续应收敛进正式文档 |
| [`_TEMP_PHASE1_5_TIMEOUT_SCAN.md`](./_TEMP_PHASE1_5_TIMEOUT_SCAN.md) | Phase 1.5 隐性超时扫描范围、结论与回归验证记录 |

仓库入口：[`../README.md`](../README.md)
