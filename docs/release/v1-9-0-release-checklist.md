# v1.9.0 发布清单

状态：已发布；annotated tag `v1.9.0` 指向发布提交，`origin/master` 与 tag 已完成推送清账

发布日期：2026-09-24

版本跨度：v1.8.0 → v1.9.0

发布形态：tag-only，不制作新的便携包或安装器

版本轴裁决：手动计划拆解新增用户可见的流式卡片体验，属于功能级增量，按仓库版本轴升级 minor 至 `1.9.0`。

## 1. Release Gate

| Gate | 判据 | 当前状态 |
|---|---|---|
| G1 | 发布前全量 pytest、Ruff、diff-check | pytest `1508 passed, 3 skipped`；仓库级 Ruff `All checks passed!`；diff-check 通过 |
| G2 | 版本轴 | `pyproject.toml` 与 `offline_companion.__version__` 已同步为 `1.9.0` |
| G3 | CHANGELOG 定稿 | `docs/CHANGELOG.md` 已形成 `v1.9.0 · 2026-09-24` 正式段 |
| G4 | README 翻转 | `docs/README.md` 已登记 v1.9.0 已发布、tag-only；B0 契约与 B4 报告保持时点快照不回翻 |
| G5 | 安装包裁决 | tag-only；流式卡片虽为用户可见能力，但当前安装包消费者接近零，打包链另立批次 |
| G6 | 发布清单落库 | 本文件按 `docs/release/v1-9-0-release-checklist.md` 落库 |
| G7 | 发布 commit 与 tag | `28d8978 chore(release): v1.9.0`；本地 annotated tag `v1.9.0` 指向该提交 |
| G8 | 推送清账 | `master` 领先提交与 annotated tag `v1.9.0` 已一次推送至 origin |
| G9 | tag 后回填 | 已回填 tag 目标 `28d8978`、推送状态与最终 gate |
| G10 | 协作档案归档 | daily 与工作区 `USER.md` 由协作方在仓库外维护，本仓库无额外动作 |

## 2. 发布范围

| 批次 | commit | 交付 |
|---|---|---|
| B0 契约 | `dcf4a89` | 十一项冻结接缝、三条 v1.3 变更记录与首版边界 |
| golden fixtures | `2237454` | 23 单例、4 条链、39 节点双实现基准 |
| B1-B3 | `215716e` | 双解析器、SSE 后端、终态采纳门与三态前端 |
| B4 收口 | `fa9c75f` | 双哨兵、候选池裁决、十一项终态报告与文档同步 |
| 发布前清债 | `69010b4` | 机械修复 5 条 import 排序和 6 条测试桩可变类属性，仓库 Ruff 清零 |
| v1.9.0 发布 | `28d8978` | 版本轴、正式 CHANGELOG、README 状态与本清单；`v1.9.0` tag 目标 |

## 3. 用户可见变化

1. 手动计划拆解可由前端以 `stream:true` 请求 SSE 流式卡片；默认同步调用保持原行为。
2. 卡片先以 provisional 状态渐进展示，只有 canonical `card_final` 才升级为 accepted。
3. 失败路径明示 retry、degraded、不可拆解或终态错误，不让 provisional 内容静默冒充已采纳计划。
4. card 事件进入全局 `seq` 与持久化，连接内 gap repair 按序补拉且不会重复累积。

## 4. 候选池终态

| 项目 | 去向 |
|---|---|
| 断开续传与 `reset` | 保留至 v1.9.x；生成生命周期与 HTTP 解耦并具备可恢复 `seq` 快照后立项 |
| Auto 拆解流式化 | 保留至 v1.9.x；Auto Mode 下次功能批且出现第二消费者时抽共享生产器 |
| 嵌套对象级流式 | 关闭；当前 1.5B schema 无对应产出和 UI 需求，避免 YAGNI |

## 5. 安装包裁决

v1.9.0 沿用 v1.8.0 的 tag-only 发布形态。仓库不生成 `OfflineCompanion-Setup-1.9.0.exe`，因此不执行打包链与安装器冒烟；根 README 中的 v1.8.0 安装器路径继续表示最近一次实际打包产物。若后续需要 v1.9.0 安装包，必须单独执行干净 Windows 便携包、Inno Setup 与安装/升级/卸载冒烟。

## 6. 发布动作

1. 已以独立提交 `69010b4` 清零 G1 Ruff 阻塞，并复现全量 `1508 passed, 3 skipped`。
2. 已创建发布提交 `28d8978 chore(release): v1.9.0`。
3. 已创建 annotated tag `v1.9.0`，目标为 `28d8978`。
4. 推送 `master` 与 `v1.9.0`；若网络失败，记录推送欠账。
5. 回填本清单的 tag 目标、推送状态和最终 gate 数字。
6. 同步 daily 与仓库外协作档案 `USER.md`。
