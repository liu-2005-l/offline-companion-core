# Offline Companion · Plugin 开发指南 v1.0（中文）

> **版本**：v1.0 · **日期**：2026-06-12  
> **英文**：[`PLUGIN_DEV_GUIDE_v1.0_en.md`](./PLUGIN_DEV_GUIDE_v1.0_en.md)  
> **架构**：[`ARCHITECTURE_v2.0_zh.md`](./ARCHITECTURE_v2.0_zh.md) · **商城**：ARCHITECTURE §四

Plugin 是运行在 **桌面壳 WebView** 中的 **前端代码片段**，通过 **声明式配置** 与 Agent 本体交互。**不增加 Agent 能力**。

> **易混项**：通用知识 RAG 是 **内置 B 层能力**，不是扩展 Plugin。见 ARCHITECTURE §五。

---

## 一、本质与边界

| | Plugin | Skill | Tool |
|---|--------|-------|------|
| 本质 | WebView 中的 JS/CSS 片段 | localhost 独立进程 | 进程内 Python 函数 |
| 清单文件 | **`plugin.json`** | **`manifest.json`** | **`manifest.json`**（规划） |
| 改什么 | 交互形态（UI） | 能力 | 可调用函数 |
| 后端通道 | **仅** `window.bridge` | 被 invoker 调用 | A2 注册调用 |
| 审计 | 前端日志 | A3 Consent | A2 三态 |

---

## 二、目录结构（最小可运行）

安装目录名 = 仓库根目录名 = `plugin.json` 中的 `name`：

```text
voice-input/                  # 仓库根 / 安装目录名
├── plugin.json               # 清单（Plugin 唯一身份入口）
├── voice-input.js            # 核心逻辑
├── voice-input.css           # 样式
├── mic.svg                   # 图标等资源
├── README.md                 # 说明
└── preview.png               # 商城预览图（可选）
```

安装路径：

```text
{data_root}/extensions/installed/voice-input/
```

**本地调试**：将整个文件夹复制到上述路径，重启桌面壳或刷新模组列表即可看到效果（与商城下载包结构 **完全一致**）。

---

## 三、`plugin.json` 契约

`plugin.json` 是 Plugin 的 **唯一身份标识与配置入口**（不是 `manifest.json`）。

### 3.1 必填字段

| 字段 | 约束 |
|------|------|
| `type` | **必须为** `"plugin"` |
| `name` | `^[a-z][a-z0-9-]*$`；与目录名一致 |
| `version` | PEP 440 release |
| `description` | 用户可见简介 |
| `ui_contributions` | UI 修改声明（§四）；**必填** |

### 3.2 推荐字段

| 字段 | 说明 |
|------|------|
| `market_id` | `{name}@{version}`；商城发布用 |
| `trust` | `user_installed` \| `bundled` \| `community_certified`（社区认证，规划） |
| `permissions` | 浏览器/Bridge 权限（§3.4） |
| `content_security_policy` | `allowed_domains`、`allow_local_fetch` |
| `assets` | 显式列出需加载的 JS/CSS 路径（可选；默认可按 `{name}.js` / `{name}.css` 约定） |

### 3.3 禁止字段

- `entrypoint`（属 Skill）  
- 任何直接写记忆 / 推理 / 出站 URL 的字段  

### 3.4 `permissions`（Plugin 侧）

| 值 | 含义 |
|----|------|
| `call_skill` | 允许通过 Bridge 调用后端 Skill |
| `microphone` | 声明需浏览器麦克风（如 `voice-input`） |

未声明的敏感能力默认 **拒绝**。具体能力门闸随 Sprint 8 `plugin_loader` 落地。

### 3.5 安全

- **禁止**直接访问文件系统、数据库、记忆库。  
- 所有后端交互 **必须** 经 `window.bridge`。  
- 出站域名仅在 `content_security_policy.allowed_domains` 声明；仍受 WebView CSP 约束。  
- 安装后 **默认禁用**；用户在设置/模组菜单启用。

### 3.6 示例 `plugin.json`

```json
{
  "type": "plugin",
  "name": "voice-input",
  "version": "1.0.0",
  "description": "语音输入：麦克风识别后填入输入框",
  "market_id": "voice-input@1.0.0",
  "trust": "user_installed",
  "permissions": ["call_skill", "microphone"],
  "ui_contributions": {
    "input_area": {
      "action": "add_button",
      "position": "right",
      "icon": "mic.svg",
      "tooltip": "语音输入",
      "on_click": "onVoiceInputClick"
    }
  },
  "content_security_policy": {
    "allowed_domains": [],
    "allow_local_fetch": true
  },
  "assets": ["voice-input.js", "voice-input.css"]
}
```

Schema 校验：`schemas/skill-manifest-v1.json` 中 `type=plugin` 分支（S8 可为 Plugin 单独提供 `plugin-manifest-v1.json`，字段对齐本文）。

---

## 四、`ui_contributions` 扩展点

Plugin **只能** 通过此字段声明 UI 修改。

### 4.1 `input_area` — 输入区按钮

```json
{
  "input_area": {
    "action": "add_button",
    "position": "right",
    "icon": "mic.svg",
    "tooltip": "语音输入",
    "on_click": "onVoiceInputClick"
  }
}
```

| 子字段 | 说明 |
|--------|------|
| `position` | `left` \| `right` |
| `icon` | 相对路径或内置图标名 |
| `tooltip` | 悬停提示 |
| `on_click` | **全局函数名**（在 Plugin JS 中定义） |

### 4.2 `auto_hook` — 事件监听

```json
{
  "auto_hook": {
    "event": "assistant_message",
    "action": "onAssistantMessage"
  }
}
```

`action` 由宿主在事件发生时调用，**助手消息文本** 作为参数（如 TTS 自动播报）。

### 4.3 规划扩展点

`sidebar`、`settings_panel`、`message_area` — Sprint 8 起版本化追加。

---

## 五、Bridge API

| API | 说明 |
|-----|------|
| `window.bridge.call_skill(name, payload)` | 调后端 Skill（**唯一**能力通道；须 `permissions` 含 `call_skill`） |
| `window.bridge.get_memory()` | 只读记忆列表 |
| `window.bridge.toggle_memory()` | 切换记忆开关 |

> 完整 Bridge：**Sprint 8** 随 `plugin_loader` 交付。

---

## 六、生命周期

```text
启动 → plugin_loader 扫描 extensions/installed/
     → 读取各目录 plugin.json（type=plugin）
     → 过滤「已启用」
     → 注入 init JSON → PluginLoader 动态加载 JS/CSS
     → 按 ui_contributions 修改 DOM

运行 → Plugin JS 响应 on_click / auto_hook
     → 需能力时 bridge.call_skill(...)

禁用/卸载 → 设置中关闭或删除目录
          → 下次启动不再加载
```

---

## 七、官方示例（Sprint 8）

| Plugin | Skill | 交互要点 |
|--------|-------|----------|
| `voice-input` | `asr-service` | 输入区麦克风；识别结果填入输入框；**用户确认后发送** |
| `voice-output` | `cosyvoice-tts` | **仅设置开关**；`assistant_message` 自动 TTS；无日常按钮 |

---

## 八、模组商城与本地加载

商城是 **分发渠道**，不是唯一入口。详见 ARCHITECTURE §四。

| 约束 | 说明 |
|------|------|
| 统一入口 | 侧栏或设置中的「模组商城」 |
| 分类 | [全部] [能力] [交互] [工具] → Skill / Plugin / Tool |
| 统一卡片 | 名称、描述、评分、安装状态；一键安装/卸载 |
| 发布 | 开发者发布到 **skill-market 独立仓库**；索引自动更新 |
| 安全扫描 | 上架前 schema 合规、文件完整性、依赖声明校验 |
| 信任标注 | 「社区认证」vs「个人发布」 |
| **本地加载** | **必备**：文件夹放入 `extensions/installed/` 即可调试 |
| 模板仓 | `plugin-template`（S8）；clone 即开发 |

**原则**：本地能跑的结构 = 商城下载的结构 = 发布包结构。

---

## 九、内置知识 RAG（非 Plugin）

| 项 | 说明 |
|----|------|
| 模块 | `core/knowledge_rag/` |
| 启用 | `configs/knowledge/default.yaml` |
| 使用 | `/search-knowledge` |

勿用 `plugin.json` 包装此能力。

---

## 十、开发 checklist

1. Clone **plugin-template**（S8 交付）。  
2. 提供 `plugin.json`（`type: plugin` + `ui_contributions`）。  
3. 能力拆到 Skill；Plugin 只 `bridge.call_skill`。  
4. 零 npm / 零框架。  
5. 本地复制到 `extensions/installed/<name>/` 手验。  
6. 上架前通过 skill-market 安全扫描。

---

## 十一、维护

Plugin 契约变更 → 本文 + schema + CHANGELOG。与 Skill 共用 `extensions/installed/`，靠 **文件名 + type** 分流：`plugin.json` → `plugin_loader`；`manifest.json` + `type=skill` → `skill_manager`。
