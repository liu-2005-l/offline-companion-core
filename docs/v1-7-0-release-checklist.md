# v1.7.0 收尾清单 v0.2

状态：v0.2（2026-08-29 版本轴校正后收尾稿）  
定位：最后一段施工的边界网——窗口布局批次的验收位置、UI 债、发布门槛与 tag 口径。  
版本跨度：v1.6.1 → v1.7.0  
版本轴裁决：repo 事实源 `pyproject.toml` 与 `offline_companion.__version__` 已在 2e1513d4 升为 `1.7.0`，且 `docs/CHANGELOG.md` 顶部已有 `v1.7.0` 记录；本次不降级回 `v1.6.0`。

## 一、Release Gate

| Gate | 判据 | 状态 |
| --- | --- | --- |
| G1 | 全量 pytest | 1168 passed, 3 skipped |
| G2 | ruff | All checks passed |
| G3 | 分层检查 | `check_imports OK` |
| G4 | `full_acceptance --skip-gpu` | 窗口批次后复验 10/10 |
| G5 | GPU 跳过项裁决 | 接受跳过：开发机无 NVIDIA GPU，GPU 非 v1.7.0 增量触点 |
| G6 | 便携包跳过项裁决 | 接受跳过：本次只推 tag，不发安装包，打包链路零变更 |
| G7 | 窗口布局验收行 | 已闭合，见 `docs/window-adaptive-layout-design.md` v3 |
| G8 | UI 债显式 | U22/U25 out of scope 在档 |
| G9 | 文档终审 | 已核：事实源在 repo，过时基线已更新，单文档未超 2 万字 |
| G10 | 版本号 + tag | 版本号已为 `1.7.0`；本收尾提交作为 `v1.7.0` tag 目标 |

## 二、已闭合范围

| 批次 | commit 链 | 基线 |
| --- | --- | --- |
| Phase 6.7 设置重构 | 先期闭合 | — |
| Phase 6.1 / 6.2 | 先期闭合，hash-bow 判别对集判决 | 1111 |
| Phase 6.3 | fcc58a8 锚点批 → 61e8b4c 主体 | 1127 |
| Phase 6.4 | d52b310 主体 → c84c821 三律哨兵 | 1138 |
| Phase 6.5 | 52333eb 敏感区 → cab395f 边界 → a9627a2 免疫区 | 1154 |
| Phase 6.6 | e82ccd4 | 1166 |
| 优化计划 v5 边界战役 | Batch A→E 全闭合 | — |
| 窗口自适应布局 | 69e5495 补齐 v3 方案事实源 + G7 哨兵 | 1168 |

## 三、版本裁定

版本裁定为 v1.7.0 minor。理由：语义记忆链路、边界不静默机制与窗口自适应布局都属于用户可感知的新能力，不是 patch 级修补；并与 v1.4.0 / v1.5.0 的 Phase 级 minor 先例一致。repo 已有 `v1.6.0` 与 `v1.6.1` tag，因此本轮发布不能复用或倒退到 v1.6.0。

## 四、CHANGELOG 框架

1. 语义记忆：自动提取语义事件、混合召回注入、情感上下文重排、显式关联事件一跳注入、高重要度字面重复 supersede、自称/画像记忆生效。
2. 记忆维护：空闲 decay GC、dormant 归档、补提取水位幂等。
3. 记忆管理界面：列表、类型筛选、删除、内容编辑、空态；手动添加与分页 out of scope。
4. 可靠性：embedding 失败降级存储、召回/GC 数据库错误不中断对话、提取超时用户无感、sqlite-vec 故障多路降级、边界输入三态判据。
5. 窗口自适应布局：per-monitor DPI 感知、假最大化不遮任务栏、多屏工作区适配；Win32 fake 验证覆盖副屏 `rcWork=(-1920,0,0,1040)`、150% fallback `1707x1019`、任务栏变化复核与越界还原夹取。
6. 内部强化：游标三律修复族、测试基线 1111 → 1168；`full_acceptance --skip-gpu` 10/10。

## 五、文档终审

| 项 | 状态 |
| --- | --- |
| 优化计划 v6 | 已加 C/D 闭合记录，并校正收尾版本轴 |
| v4 / v5 计划留档 | v5 已由 v6 接替；v4/v5 旧档不再回写同步 |
| `window-adaptive-layout-design.md` v3 | 已在 repo，含验证数据归档 |
| `oc-refactor-phase6-test.md` / phase6-5 fixtures | 已同步 1168 终基线与 out-of-scope 口径 |
| README / docs README | 当前版本沿用 `1.7.0`，文档导航补 release checklist 与窗口方案 |
| 全量约束 | 单文档未超 2 万字；收尾文档不写排期 |

## 六、裁决位

G5 GPU 跳过项：接受跳过。理由：开发机无 NVIDIA GPU，本地推理链路 CPU 路径已由全量测试与 `full_acceptance` 覆盖；GPU 路径非 v1.7.0 增量触点。

G6 便携包跳过项：接受跳过。理由：本次发布形态为 tag，不发安装包；本周期打包链路（PyInstaller spec / Inno Setup 脚本）无变更，便携包验证推迟至下次分发。

## 七、已知债务

| 债务 | 来源 | 目标 |
| --- | --- | --- |
| U22 手动添加事件 / U25 100+ 分页 | 6.5 UI 收窄 | v1.8.0+ UI 补全批 |
| related 0.70 语义关联 | 6.2 判决 + 6.6 W10 两层裁决 | v1.8.0+ |
| 真 semantic embedding | 6.2 判决 | v1.8.0+ |
| expansion 休眠能力 | 6.3 | v1.8.0+ |
| SSE 切片非真 token 流 | 老债 | v1.8.0+ |
| E3 多轮指代 | 红队矩阵 | v1.8.0+ |
| 多工具链完整执行 | 红队/拆解链遗留 | v1.8.0+ |
| EventRecaller 实例复用复检 | 6.3 | v1.8.0+ |
| 两路 hash-bow 冗余简化 | 6.3 | v1.8.0+ |
| plan_store / extension toggle 等老债 | 内部文档已有记档 | 引用既有记档 |

## 八、执行顺序

1. 窗口布局批次施工并填充 G7。✅
2. G1-G4 全量重跑。✅
3. G5 / G6 裁决落档。✅
4. 版本号、CHANGELOG 与 tag。✅
5. 文档终审。✅
6. 发布 / 推送。tag 本地落档，远端推送另行执行
