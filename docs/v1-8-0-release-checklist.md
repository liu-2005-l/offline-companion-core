# v1.8.0 收尾清单 v0.1

状态：v0.1（2026-08-30 V1-D 收口稿）  
定位：真 semantic embedding V1 批次的发布边界网。  
版本跨度：v1.7.0 → v1.8.0  
版本轴裁决：semantic recall 从字面匹配升级为真 embedding 召回，属于用户可感知功能级增量，按 repo 轴升为 `1.8.0`。

## 一、Release Gate

| Gate | 判据 | 状态 |
| --- | --- | --- |
| G1 | 全量 pytest | 1187 passed, 3 skipped |
| G2 | ruff | All checks passed |
| G3 | 分层检查 | `check_imports OK` |
| G4 | `full_acceptance --skip-gpu` | 模型在场环境复验 10/10 |
| G5 | GPU 跳过项裁决 | 沿用 v1.7：开发机无 NVIDIA GPU，GPU 非本批增量触点 |
| G6 | 便携包跳过项裁决 | 本批只落 tag 口径；若发安装包，另跑干净 Windows 打包链验收 |
| G7 | 模型资产验收 | ONNX fp32 `model.onnx` SHA256 已校验；tokenizer 原子落盘 |
| G8 | C2 判决资产 | `fixtures/v1_8_semantic_embedding_c2_scores.json` 在 repo，记录分布、sweep 与 R43-R46 分数 |
| G9 | 文档终审 | CHANGELOG、V1 方案、fixture 文档与 docs 导航已同步 |
| G10 | 版本号 + tag | ✅ `pyproject.toml` 与 `offline_companion.__version__` 为 `1.8.0`；`v1.8.0` tag 已推送，目标 `1084c13` |

## 二、已闭合范围

| 批次 | commit 链 | 基线 |
| --- | --- | --- |
| Phase A 预注册锚 | 3bcd7e2 | 1173 |
| Phase B provider + 入口收口 | d702c6d | 1179 |
| Phase C1/C2 模型接入与阈值裁决 | 509dbe7 | 1185 |
| Phase C3-C5 followup | 1fcf617 | 1187 |
| Phase D 收口 | 本收尾提交 | 1187 |

## 三、版本裁定

版本裁定为 v1.8.0 minor。理由：semantic recall 由 deterministic hash-bow/词面近似升级为 ONNX 真 embedding 召回，并新增模型下载、空间标签、启动重算与可解释降级；这是功能级新能力，不是 patch 修复。

## 四、CHANGELOG 用户口径

1. 记忆召回从字面匹配升级为语义匹配：判别对集同义改写命中 `29/31`（94%），dissimilar 误报 `0/40`。
2. 未下载或加载失败时自动回退 hash-bow 字面匹配，只打一条 warning，不阻断、不上云。
3. 语义事件向量带空间标签，召回只比较同空间数据，避免 hash-bow 与 ONNX 向量混源产生垃圾分。
4. 写端重复检测保持文本 Jaccard 字面去重，未把 semantic recall 阈值静默扩散到去重语义。
5. R43-R46 与 C2 sweep 作为后续模型升级/reranker 触发器：排序倒挂未清零前不宣称全语义召回。

## 五、文档终审

| 项 | 状态 |
| --- | --- |
| `docs/CHANGELOG.md` | 已新增 v1.8.0 记录 |
| `docs/v1-8-0-batch-v1-semantic-embedding-design.md` | 已记录 C1-C5 与 C2 排序倒挂裁决 |
| `docs/phase6-5-recall-injection-fixtures.md` | 已同步 F2 semantic 实测与阈值拆分 |
| `docs/README.md` | 已挂 v1.8.0 收尾清单 |
| 版本事实源 | `pyproject.toml` / `offline_companion.__version__` / 桌面 about 文案同步为 `1.8.0` |

## 六、已知债务

| 债务 | 来源 | 目标 |
| --- | --- | --- |
| semantic duplicate 去重独立校准 | C2 dup 漂移修回 | v1.8.x |
| bge-large / bge-m3 模型升级触发器 | C2 排序倒挂 | v1.8.x |
| cross-encoder reranker | C2 bi-encoder 倒挂 | v1.8.x |
| expansion 接线决策 | 6.3 休眠能力 + V1 模型到位 | v1.8.x |
| 两路 hash-bow 冗余简化 | 6.3 anchor 分歧度 | v1.8.x |
| U22/U25 UI 补全、SSE 真流、E3、多工具链 | v1.7 债务池 | 后续独立批 |

## 七、发布动作

1. 收尾提交锁定 1187 基线。
2. 已创建并推送 `v1.8.0` tag，目标 `1084c13`。
3. 若决定发安装包，先执行干净 Windows 便携包/安装器验收；否则沿用 tag-only 口径。
