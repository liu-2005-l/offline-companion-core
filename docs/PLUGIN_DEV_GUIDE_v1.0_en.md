# Offline Companion · Plugin Developer Guide v1.0 (English)

> **Date**: 2026-06-12 · **中文**: [`PLUGIN_DEV_GUIDE_v1.0_zh.md`](./PLUGIN_DEV_GUIDE_v1.0_zh.md)

Plugins are **frontend snippets** in the desktop **WebView**, configured declaratively. They **cannot** add Agent capabilities.

---

## Essence

| | Plugin | Skill |
|---|--------|-------|
| Manifest | **`plugin.json`** | **`manifest.json`** |
| Runtime | WebView JS/CSS | localhost process |
| Backend | `window.bridge` only | invoked by host |

---

## Minimal layout

```text
voice-input/
├── plugin.json
├── voice-input.js
├── voice-input.css
├── mic.svg
├── README.md
└── preview.png   # optional mall preview
```

Install: `{data_root}/extensions/installed/voice-input/`

**Local dev**: copy folder there; restart or refresh — same layout as mall download.

---

## `plugin.json`

**Required**: `type: "plugin"`, `name`, `version`, `description`, `ui_contributions`.

**Optional**: `market_id`, `trust`, `permissions` (`call_skill`, `microphone`), `content_security_policy`, `assets`.

**Forbidden**: `entrypoint`, direct memory/inference fields.

Default **disabled** after install. No direct FS/DB access.

---

## `ui_contributions`

- `input_area.add_button` — `position`, `icon`, `tooltip`, `on_click` (global fn)  
- `auto_hook.assistant_message` — `action(msgText)`  

---

## Bridge (Sprint 8)

`call_skill` · `get_memory` (read-only) · `toggle_memory`

---

## Lifecycle

Scan `extensions/installed/` → read `plugin.json` → enabled only → inject JS/CSS → apply contributions → bridge for Skills.

---

## Mod marketplace

Optional distribution via **skill-market** repo; **local folder install is mandatory** for dev. Unified cards; filters: All / Capability / Interaction / Tool. See ARCHITECTURE §4.

**Authority**: Chinese guide on ambiguity.
