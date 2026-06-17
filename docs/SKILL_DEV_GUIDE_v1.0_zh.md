# Offline Companion · Skill 开发指南 v1.0（中文）

> **版本**：v1.0 · **日期**：2026-06-12  
> **英文**：[`SKILL_DEV_GUIDE_v1.0_en.md`](./SKILL_DEV_GUIDE_v1.0_en.md)  
> **架构**：[`ARCHITECTURE_v2.0_zh.md`](./ARCHITECTURE_v2.0_zh.md) · **Schema**：[`schemas/skill-manifest-v1.json`](../schemas/skill-manifest-v1.json)

Skill 扩展 **Agent 能力**（能做什么），以 **独立进程 + localhost API** 运行。**不修改 UI**。

清单文件为 **`manifest.json`**（Plugin 使用 **`plugin.json`**，见 PLUGIN_DEV_GUIDE）。

---

## 一、与 Plugin / Tool 的边界

| | Skill | Plugin | Tool |
|---|-------|--------|------|
| 清单 | **`manifest.json`** | **`plugin.json`** | `manifest.json`（规划） |
| 改什么 | 能力 | 交互 UI | 进程内函数 |
| UI | **禁止** `ui_contributions` | 必须 `ui_contributions` | 无 UI |
| 联网 | 可，经 A3 | 禁止直联；经 Bridge/Skill | 依级别 |
| 记忆 | 默认不写 B2 | — | 不进 B2 |

---

## 二、Manifest 契约

### 2.1 通用字段（与扩展 manifest 共用）

| 字段 | 约束 |
|------|------|
| `type` | **必须为** `"skill"`（纪要；schema 7.1 收尾加入） |
| `name` | `^[a-z][a-z0-9-]*$` |
| `version` | PEP 440 → `packaging.version.Version` |
| `market_id` | `{name}@{version}` |
| `trust` | `user_installed` \| `bundled` |
| `description` | 用户可见简介 |

### 2.2 Skill 专有字段

| 字段 | 约束 |
|------|------|
| `entrypoint` | `local_api`；`host` 仅 `127.0.0.1`；`path` 以 `/` 开头 |
| `permissions` | `cloud_inference` \| `network_egress` \| `read_session_context` |
| `required_api_keys` | 小写蛇形；宿主注入 `OFFLINE_COMPANION_SKILL_KEY_<NAME>` |
| `output_mode` | `stream` \| `block` |

**禁止**：`write_memory`；**禁止**：`ui_contributions`（属 Plugin）。

### 2.3 占位字段（7.1 收尾 · 不实现校验逻辑）

| 字段 | 用途 |
|------|------|
| `error_codes` | 扩展错误码字典（S8 规范落地） |
| `content_security_policy` | 预留；Skill 不用，Plugin 用；统一 schema 占位 |

### 2.4 权限

| 权限 | 行为 |
|------|------|
| `cloud_inference` | Consent `skill_cloud_call`（每条 manifest 至多触发一条云端 Consent） |
| `network_egress` | 出站；`LOCAL_ONLY` **硬拒** |
| `read_session_context` | 远期；MVP `check_read_context()` 恒 False |

### 2.5 示例

见 `fixtures/skills/novel-writer/manifest.json`（待补 `"type": "skill"`）。

```json
{
  "type": "skill",
  "name": "novel-writer",
  "version": "1.2.0",
  "description": "辅助长篇小说创作",
  "market_id": "novel-writer@1.2.0",
  "trust": "user_installed",
  "entrypoint": {
    "type": "local_api",
    "host": "127.0.0.1",
    "port": 9101,
    "path": "/v1/complete"
  },
  "permissions": ["cloud_inference"],
  "required_api_keys": ["deepseek"],
  "output_mode": "block"
}
```

---

## 三、目录与安装

```text
novel-writer/                     # 仓库根 = 安装目录名
├── manifest.json                 # Skill 清单（非 plugin.json）
├── … 服务代码与资源 …
├── README.md
└── preview.png                   # 商城预览图（可选）
```

安装路径：`{data_root}/extensions/installed/<name>/`

`skill_manager` 扫描各子目录的 **`manifest.json`**，**仅加载** `type: skill`。  
`plugin.json`（Plugin）与 Tool 清单由各自加载器处理（S8 / S9+）。

**本地调试**：文件夹放入 `extensions/installed/` 即可，结构与商城下载包一致（见 ARCHITECTURE §四）。

---

## 四、Policy（7.1 ✅）

| 隐私模式 | 权限 | 结果 |
|----------|------|------|
| `LOCAL_ONLY` | `network_egress` 或 `cloud_inference` | 硬拒 |
| 其他 | `cloud_inference` | 允许 + `skill_cloud_call` |
| 其他 | 仅本地 | `skill_invoke` |

实现：`shell/skill_manager/policy.py`。

---

## 五、调用链（7.5 目标）

```text
用户 → B3 → A2 router → policy → [A3 Consent] → invoker(127.0.0.1) → B4 → 落库
```

- Invoker 管理子进程 PID；仅 localhost HTTP。  
- Plugin 调 Skill：**仅** `window.bridge.call_skill(name, payload)`（宿主 Bridge 实现属 Sprint 8）。

---

## 六、Consent `purpose_type`（7.2）

| 类型 | 场景 |
|------|------|
| `skill_invoke` | 纯本地 |
| `skill_cloud_call` | 含 `cloud_inference` |
| `skill_market_index` | 商城索引 |
| `skill_market_download` | 拉包 |

商城 API：**skill-market 独立仓库** — `GET /v1/skills`、`POST /v1/download/{id}`，均经 A3。

---

## 七、Sprint 7 路线图

| 子项 | 状态 |
|------|------|
| 7.0 schema | ✅ |
| 7.1 registry / policy | ✅ 代码基准 |
| 7.1 收尾 | `type`、CSP/error 占位、`extensions/installed/` | ✅ |
| 7.2 Consent + API Key | 待做 |
| 7.3 skill-market 独立仓 | 待做 |
| 7.4 novel-writer | 待做 |
| 7.5 `/skill` CLI | 待做 |
| 7.6 评测 + check_imports | 部分 |

验收：`pytest tests/test_skill_manager.py`；B/C 不得 import `skill_manager`。

---

## 八、语音 Skill 示例（S8）

| Skill | permissions | 说明 |
|-------|-------------|------|
| `cosyvoice-tts` | `[]` | CosyVoice 本地 TTS；配合 Plugin `voice-output` |
| `asr-service` | `[]` | 本地 ASR；配合 Plugin `voice-input` |

---

## 九、开发 checklist

1. `manifest.json` 含 `"type": "skill"`，无 `ui_contributions`。  
2. HTTP 服务仅绑定 `127.0.0.1`。  
3. 最小权限；云端路径单独测 Consent。  
4. 使用 **skill-template** 独立模板仓（S8 交付）。  
5. 宿主仓跑 skill_manager 测试。

---

## 十、调试

| 步骤 | 命令 / 操作 |
|------|-------------|
| 安装可选依赖 | `pip install -e ".[skill]"` |
| 校验 manifest | `load_skill_manifest(path)` |
| 单测 | `pytest tests/test_skill_manager.py -q` |
| 本地起 Skill | 按 entrypoint 起服务后 curl `http://127.0.0.1:<port><path>` |
| Policy 手测 | `evaluate_skill_policy(manifest, privacy_mode=...)` |

---

## 十一、维护

契约变更 → 本文 + schema + CHANGELOG。架构原则见 ARCHITECTURE，不在此重复。
