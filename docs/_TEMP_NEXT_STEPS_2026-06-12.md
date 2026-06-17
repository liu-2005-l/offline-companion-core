# 临时：文档与代码冲突 · 下一步行动清单

> **性质**：过渡文档；闭合后 **删除**。  
> **权威架构**：[`ARCHITECTURE_v2.0_zh.md`](./ARCHITECTURE_v2.0_zh.md)  
> **定稿核对**：2026-06-12 确认（方案 B、7.1 一次性改路径）

---

## 一、冲突项状态

| # | 冲突点 | 定稿决策 | 状态 |
|---|--------|----------|------|
| 1 | 安装目录 | **方案 B**：`extensions/installed/`，7.1 一次性改，无过渡别名 | ✅ 7.1 收尾已落地 |
| 2 | `type` 字段 | Schema 必填；registry 按 type 分流（skill_manager 仅 `skill`） | ✅ 7.1 收尾已落地 |
| 3 | CSP / 错误码 | 可选占位，不实现校验 | ✅ schema 已加 |
| 4 | Plugin 加载器 | Sprint 8；读 **`plugin.json`**（非 manifest.json） | ⏳ 待做 |
| 11 | Plugin 清单文件名 | 文档定稿 `plugin.json`；7.1 schema 仍名 skill-manifest-v1 | ⏳ S8 对齐 schema/loader |
| 5 | Tool 注册表 | Sprint 9+ | ⏳ 待做 |
| 6 | 模组商城 | skill-market 独立仓；Mall UI 侧栏占位，S8 激活 | ⏳ 7.3 + 8 |
| 7 | Bridge API | 随 Plugin 加载器 Sprint 8 | ⏳ 待做 |
| 8 | 知识 RAG | 内置能力，不改模块路径 | ✅ 已定稿 |
| 9 | 模板仓 | Sprint 8 与文档同步 | ⏳ 待做 |
| 10 | 截图 | 真实 UI 后补，不伪造 | ⏳ Sprint 8 |

---

## 二、含糊议题（已冻结）

| 议题 | 定稿 |
|------|------|
| B1 压缩摘要 | **入库** `memory_chunks`，`context_summary`，用户可删 |
| Plugin 定义 | **仅** WebView 动态 UI；知识 RAG ≠ Plugin |
| 7.3 商城 | **skill-market 独立仓库**；宿主 Mall UI + A3 下载；本地文件夹加载必备 |
| Plugin 清单 | **`plugin.json`** + 目录结构规范 | Skill 用 `manifest.json` |
| `architecture_v1.0.md` | **保留只读** 历史基线 |

---

## 三、后续执行顺序

### Sprint 7.2

1. Consent `purpose_type` 四类 + `OFFLINE_COMPANION_SKILL_KEY_<NAME>` 宿主注入。

### Sprint 7.3–7.6

2. skill-market 独立仓 MVP（下载写入 `extensions/installed/`）。  
3. novel-writer；`/skill` CLI；check_imports 扩展。

### Sprint 8

4. `plugin_loader` + PluginLoader JS + Bridge；**一并落地** `permissions` 门闸（`call_skill`、`microphone` 等）与 `trust` 信任等级（含 `community_certified`）。  
5. 模组商城 UI 激活。  
6. 扩展错误码规范（启用 schema 占位校验）。  
7. CosyVoice + voice-output 示例；skill-template / plugin-template 仓。  
8. USER_MANUAL 截图；**删除本文件**。

### Sprint 9+

9. Tool 机制；Pipeline；被动画像；桌面小人；PlanNotebook。

---

## 四、删除本文件的条件

- [x] `extensions/installed` 与 manifest `type` 已在代码与 schema 落地  
- [x] CSP / 错误码占位已在 schema 存在  
- [ ] Sprint 8 plugin_loader 有测试或手验条目  
- [ ] CHANGELOG 记录「7.1 收尾闭合」  

完成后从 `docs/README.md` 移除链接并删除本文件。
