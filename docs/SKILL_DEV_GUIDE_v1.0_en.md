# Offline Companion · Skill Developer Guide v1.0 (English)

> **Date**: 2026-06-12 · **中文**: [`SKILL_DEV_GUIDE_v1.0_zh.md`](./SKILL_DEV_GUIDE_v1.0_zh.md)

Skills extend **what the Agent can do** via **localhost API processes**. Manifest: **`manifest.json`** (Plugins use **`plugin.json`**). **No UI** — no `ui_contributions`.

---

## Boundary

| | Skill | Plugin | Tool |
|---|-------|--------|------|
| Changes | capabilities | UI | in-process functions |
| UI | forbidden | required contributions | none |

---

## Manifest

- `type`: **must be** `"skill"` (schema update in 7.1 wrap-up)  
- `entrypoint`: `local_api` @ `127.0.0.1` only  
- `permissions`: `cloud_inference` | `network_egress` | `read_session_context`  
- Placeholders (no validation yet): `error_codes`, `content_security_policy`  
- Forbidden: `ui_contributions`, `write_memory`

Install target: `{data_root}/extensions/installed/<name>/`. `skill_manager` loads only `type: skill`.

---

## Policy (7.1 ✅)

`LOCAL_ONLY` hard-denies network/cloud permissions. See `policy.py`.

---

## Consent (7.2)

`skill_invoke` | `skill_cloud_call` | `skill_market_index` | `skill_market_download`  
Market API from **separate skill-market repo**.

---

## Sprint 7

7.1 ✅ registry/policy · wrap-up: `type`/CSP/error placeholders · 7.2 Consent · 7.3 market · 7.4 novel-writer · 7.5 `/skill` CLI.

---

## Voice examples (S8)

`cosyvoice-tts` + `asr-service` Skills (local, `permissions: []`).

---

## Debug

`pip install -e ".[skill]"` · `pytest tests/test_skill_manager.py -q` · curl localhost entrypoint.

**Authority**: Chinese guide on ambiguity.
