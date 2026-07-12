# Offline Companion · Architecture v2.0 (English)

> **Version**: v2.0 · **Date**: 2026-06-12  
> **Historical baseline**: [`architecture_v1.0.md`](./architecture_v1.0.md) (read-only; this doc wins on conflict)  
> **中文**: [`ARCHITECTURE_v2.0_zh.md`](./ARCHITECTURE_v2.0_zh.md)  
> **Temp code gaps**: [`_TEMP_NEXT_STEPS_2026-06-12.md`](./_TEMP_NEXT_STEPS_2026-06-12.md)

---

## 1. Core principles

Companion first; extensions second; transparent memory; privacy first; auditable egress via A2+A3; B/C network ban via `check_imports`; **B4 is the final output gate**; **brain-body separation**: Agent core (B/C + A2 orchestration) handles task understanding, planning & decomposition; agent-toolbox Skill executes actions.

---

## 2. Layering (Agent core)

A Policy Shell (`shell/`) · B Companion Core (`core/`) · C Inference & IO (`runtime/`).  
Forbidden: `B→A`, `C→A`, `C→B`; B/C must not import network libraries.  
B/C layers communicate with A layer via a unified Message Bus, sending/receiving standardized messages (BaseMessage) only, unaware of transport protocol. All cross-layer communication uses unified BaseMessage format (with `role`, `content`, `meta`, `timestamp`), regardless of whether the underlying transport is function call, HTTP, or message queue — message structure remains consistent. `content` field supports `text`, `image_url`, `audio_buffer` and other types. Current MVP implements `text` only; remaining types are protocol-layer placeholders for future multimodal Skill integration.

C2 storage: vector writes land in SQLite `vector_queue` table first (WAL journal), background thread asynchronously updates vector index. On vector DB crash, SQLite is the complete data source. Provides `reindex` command to rebuild full vectors when embedding model changes.

### Single-turn companion path

```
User input → B3 safety (block → fixed reply)
          → [S8+] A2 dynamic sandbox / session gap
          → B2 recall (memory on; active only)
          → B1 assemble_reply → [S8+] async context compression
          → C1 generate → B4 → persist
```

### Complex task path

```
User complex goal → A2 PlanOrchestrator
  ├─ Task decomposition: break goal into ordered steps (Step 1 → Step 2 → Step 3)
  ├─ Dependency management: declare data dependencies between steps
  ├─ State tracking: pending / running / done / failed per step
  ├─ Error recovery: retry strategy or fallback path on failure
  └─ Context passing: TaskContext for intermediate results
```
TaskContext: a temporary, task-bound data space. Skills read/write this context during execution; upon completion, key results may be written to B2 memory (`#remember`), the rest discarded. PlanOrchestrator still goes through A3 Consent when calling Skills; B/C layers are unaware of plans.

---

## 3. Skill / Plugin / Tool

| Type | Changes | Runtime | Security | Audit |
|------|---------|---------|----------|-------|
| **Skill** | Capabilities | localhost API process | sandbox + A3 Consent | A3 |
| **Plugin** | UI experience | WebView JS/CSS | CSP + Bridge | frontend log |
| **Tool** | Callable functions | in-process Python | builtin/certified/external | A2 tri-state |

- Skill: **no** `ui_contributions`; may use network via A3.  
- **agent-toolbox super Skill**: a Docker-sandboxed Python service integrating Playwright browser automation, code execution, filesystem ops, and network requests. Agent core (brain) delegates actions to it (body) via A2 orchestrator, fully gated by A3 Consent.  
- **Message queue mode**: agent-toolbox communicates with core via HTTP by default, but supports upgrade to ZeroMQ or nanomsg message queue mode. In message queue mode, Skills publish messages to topics; A2 `MessageRouter` acts as message broker for routing; long-running task results and progress updates are pushed asynchronously via queue, without blocking current conversation flow. B/C layers are unaware of communication mode switching.  
- **agent-toolbox supports two modes**: Docker mode (production, high isolation) and Native process mode (dev/debug, low barrier). If Docker is unavailable on install, auto-fallback to Native mode with Consent dialog warning about isolation differences.  
- **Seamless Docker-unavailable experience**: On agent-toolbox startup, auto-detect Docker status. If not installed or not running, auto-switch to Native mode and show "Sandbox not enabled (running directly on system)" in bottom bar. No blocking dialog; retain manual switch to Docker mode entry.  
- **Native mode safety prompt**: Native mode Consent dialog uses orange/red border labeling "This mod will run directly on your system and may access your files." On install, installer checks manifest for `network_egress` declaration and prompts user confirmation. This prompt logic belongs to A3 Consent generation phase, no B/C layer changes.  
- **Each Skill uses its own Python virtual environment** (`extensions/installed/<skill-name>/.venv/`) to avoid dependency conflicts. Skill manifest declares dependencies; venv is auto-created and `pip install`-ed on install.  
- **Dependency security**: Skill `requirements.txt` must lock dependency hashes (`package==version --hash=sha256:...`). Installer verifies hashes; mismatch rejects install and prompts user. After install, auto-generates SBOM at `extensions/installed/<skill-name>/sbom.json` for user audit.  
- **Skill may declare `output_mode: "raw"`** (e.g., code generation, data analysis, agent-toolbox results). In this mode, B4 performs format safety checks only, without injecting persona-style polish.  
- Plugin: **cannot** add capabilities; uses `window.bridge.call_skill`.  
- Tool: no separate process; no runtime registration UI; results not in memory.  
- Unified install: `{data_root}/extensions/installed/<name>/`.  
- Manifest: Skill/Tool → `manifest.json`; Plugin → **`plugin.json`**.  
- User-facing name: **mods (模组)**; internal loaders must not mix.

---

## 4. Mod marketplace

Distribution channel, not the only entry. **Local folder install is required** for dev.

- UI: sidebar/settings mall entry; community picks; unified cards (name, desc, rating, status)  
- Filters: All / Capability / Interaction / Tool  
- Publish: skill-market repo; security scan; trust labels (certified vs user)  
- Local load: copy folder to `extensions/installed/` — same layout as mall package  
- **Install experience**: User clicks install → download, extract, create venv, install dependencies fully automated; progress shown as progress bar on card. Mod auto-enables after install, no manual steps. On dependency install failure, card shows "One-click fix" button for auto-retry or manual intervention prompt | backlog  
- **Lazy loading**: After install, process and model not started immediately; first Skill call triggers startup. Install only completes file extraction and dependency installation, no extra resource consumption | backlog  
- **Built-in mods**: 3 official killer Skills pre-installed: ① Local code interpreter (Docker sandbox, reuses agent-toolbox); ② Private knowledge base assistant (calls RAG API); ③ Automated life manager (calls PlanOrchestrator). Visible on first marketplace open | backlog

---

## 5. Built-in capabilities (not extension Plugins)

- Personal memory RAG (`#remember`, FTS, decay); **Hybrid search**: memory recall combines vector semantic search + BM25 keyword matching + SQLite FTS5 full-text search, three-way recall with fused ranking. AI responses include citation markers (e.g., [1] [2]), user can click to jump to original snippet.  
- General knowledge RAG (`knowledge.db`, `/search-knowledge`, off by default); supports hot-cold knowledge separation — hot knowledge (recent docs, today's todos) kept in memory or SQLite FTS5 for millisecond recall; cold knowledge (old diaries, archived emails) stored on disk vector DB, retrieved only during deep review. RAG capabilities exposed as independent service API for Skills (e.g., novel-writer) to call, enabling knowledge reuse.  
- Optional memory embeddings (`embedding.yaml`, off by default); supports hot-cold separation — recent N days (hot data) kept in memory or SQLite FTS5 fast index, old data (cold data) archived to disk, loaded only on explicit `#recall` or deep search. Hot data window size configurable in `embedding.yaml`.

---

## 6. Agent consensus

### 6.1 Desktop shell (A1)

| Item | Consensus | Status |
|------|-----------|--------|
| Tech | pywebview + HTML/CSS/JS; 127.0.0.1; in-process orchestrator | ✅ |
| Layout | sidebar + main + bottom bar (VS Code style) | ✅ |
| Sidebar | Chat/Persona/Mods/Memory/Settings; PoC only chat active | ✅ mods placeholder |
| Bottom bar | Privacy, memory toggle, model status | ✅ |
| Lifecycle | Close→tray; single instance | ✅ |
| UI | Sakura pink; Consent Codex cards | ✅ |
| Dev host | Flask `web` non-production acceptance | ✅ |
| Hardware detection | Auto-detect GPU VRAM / RAM / disk before install; VRAM ≥8GB recommends full-feature mode, 4-6GB warns some advanced features limited (IdleThink, CosyVoice), <4GB recommends pure CPU mode + disk vector optimization | 🔲 待做 |
| Honest prompt | Enabling proactive thinking features (IdleThink, GoalManager) requires ≥6GB VRAM; if not met, gray out the option in settings with label "Not supported by current hardware" | 🔲 待做 |
| Status visualization | When IdleThink runs in background, tray icon or corner character uses breathing light effect; Skill call shows "executing task" animation; long idle → character enters "standby" pose. Users perceive AI state through these micro-interactions without checking logs | 🔲 待做 |

### 6.2 A2 Policy

**A2 internal module call order**: Each request entering A2 layer passes through modules in the following sequence:

```text
User input / system event
  → A2 Router LLM (intent routing: chat / lookup / execute code)
    → A2 Policy (dynamic sandbox + session gap + LOCAL_ONLY check)
      → A2 Consent (egress permission check, only when egress needed)
        → A2 skill_manager (call target Skill)
          → A2 invoker (execute Skill + circuit breaker check)
            → A2 PlanOrchestrator (complex task decomposition, optional)
              → A2 GoalManager (long-term goal evaluation, optional)
                → A2 AttentionAwareness (reminder filtering + attention awareness)
                  → A2 ResourceArbitrator (system resource check)
                    → A2 MessageRouter (route message to B/C layer or UI)
```

- Each module can be skipped (e.g., simple chat skips PlanOrchestrator).
- Modules communicate via unified BaseMessage, no shared mutable state.
- This is a logical order; implementation allows independent enable/disable per module.

| Item | Consensus | Status |
|------|-----------|--------|
| Dynamic sandbox | Temp constraints injected into prompt; not in memory; this round/today/duration | 📅 S8+ |
| Session gap | B2 `last_active_at`; injected before assembly | 📅 S8+ |
| LOCAL_ONLY | Hard deny `network_egress` / `cloud_inference` | ✅ Skill policy |
| Tool tri-state | ALLOW / ASK / DENY (PermissionEngine future) | 📅 S9+ Tool |

### 6.3 B2 Memory

| Item | Consensus | Status |
|------|-----------|--------|
| Write | Single `#remember` gate; compressed summary deletable | ✅ gate |
| `memory_type` | `fact` / `habit` / `preference` / `context_summary` | backlog |
| `status` | `active` / `cancelled`; recall only active | backlog |
| Habit cancel | Conflict→mark cancelled, no new entry | backlog |
| Timestamps | `memory_chunks`, `messages` both `created_at` | partial |
| Decay | Recent higher; distant lower but not zero | ✅ |
| Compressed summary | `fidelity`, `round_range`, `compression_batch` (int, e.g. `26061101`) | backlog |
| Compression principle | Based on original dialogue; no re-compression; by round range | backlog |
| Priority | User facts > Agent persona > Chat history | ✅ |

### 6.4 B1 Context compression (S8+)

- **Trigger**: token exceeds **80%** window → compress to **60%**.
- **Keep**: persona iron rules + recent **N** rounds verbatim + current recall memory blocks.
- **Execution**: **async**, does not block current turn reply.
- **Summary to DB**: `memory_chunks`, `memory_type=context_summary`, user deletable.

### 6.5 B3 & A2 sandbox

- **B3**: system hard boundary; `configs/safety_replies/`; user cannot modify.
- **A2 sandbox**: user temp constraints; "today" → sandbox, "from now on/forever" → habit memory.

### 6.6 A3 Consent

Codex cards; sakura pink. This document is self-contained for `purpose_type`; all egress, sandbox downgrade, high-risk Plugin/Tool calls, and Native risk prompts use one unified audit table.

| `purpose_type` | Trigger | Audit fields | Validity | Reusable |
|---|---|---|---|---|
| `skill_network_egress` | Skill declares network access | `skill_id`, `domain_allowlist`, `reason` | single session | No |
| `skill_file_access` | Skill declares external file access | `skill_id`, `path_allowlist`, `reason` | single session | No |
| `skill_code_execution` | Skill declares code execution | `skill_id`, `runtime`, `reason` | single session | No |
| `skill_cloud_inference` | Skill requires cloud inference | `skill_id`, `model`, `reason` | single session | No |
| `cloud_routing` | AutoRouter chooses cloud model | `model_name`, `token_estimate`, `cost_estimate`, `reason` | single session | No |
| `sandbox_downgrade` | CubeSandbox → Docker → Native downgrade | `from_mode`, `to_mode`, `reason` | single session | No |
| `native_risk_prompt` | Native mode risk warning | `skill_id`, `risk_level`, `reason` | single session | No |
| `plugin_high_risk_skill` | Plugin calls a high-risk Skill | `plugin_id`, `skill_id`, `risk_level`, `reason` | single session | No |
| `tool_external_enable` | Explicitly enable external Tool | `tool_name`, `scope`, `reason` | single session | No |
| `agent_toolbox_high_risk` | High-risk agent-toolbox invocation | `caller_skill_id`, `operation`, `reason` | single session | No |

**Note**: `purpose_type` is always one-shot audited; all records store `created_at`, `trace_id`, and `actor`.

### 6.7 A2 PlanOrchestrator (S9)

Task planning & execution monitoring core, decomposing complex user goals into executable step sequences.

| Item | Consensus | Status |
|------|-----------|--------|
| Task decomposition | Break goal into ordered steps (Step 1 → Step 2 → Step 3) | 📅 S9A |
| Dependency management | Declare data dependencies between steps | 📅 S9A |
| State tracking | pending / running / done / failed per step | 📅 S9A |
| Error recovery | Retry strategy or fallback path on failure; each step may declare `idempotent` flag — idempotent steps reuse cached results on retry, non-idempotent steps skip directly or ask user confirmation | 📅 S9A |
| TaskContext | Temp data space; Skills read/write during execution; optional write to B2 memory on completion | 📅 S9A |
| A3 relationship | Still goes through A3 Consent when calling Skills; B/C layers unaware | 📅 S9A |

**PlanNotebook**: frontend UI for PlanOrchestrator — user-visible plan management interface (desktop shell sidebar or settings) for viewing progress, pausing/resuming/canceling plans.

### 6.8 A2 GoalManager (S9)

Long-term goal management subsystem, evolving Agent from "passive responder" to "proactive companion".

| Item | Consensus | Status |
|------|-----------|--------|
| Goal storage | User long-term goals stored in B2 memory, `memory_type: goal` | 📅 S9B |
| Progress evaluation | Periodically evaluate goal progress (when, what to check) | 📅 S9B |
| Trigger reminder | When conditions met, proactively mention via B1 prompt assembly | 📅 S9B |
| Frequency control | Hard cap on proactive reminders (e.g., max once per hour), user can disable | 📅 S9B |
| Reminder decision | Utility function: Utility = Value_of_Reminder - Cost_of_Distraction. Low-utility reminders auto-degrade (popup → tray icon blink) when user is focused; high-utility reminders (user-explicit urgent) unrestricted | 📅 S9B |

### 6.9 C-layer IdleThink loop (S9)

Background proactive thinking loop, driven by GoalManager.

```
Idle detection → user N minutes inactive
  → Check for active long-term goals
  → Evaluate if current context relates to goals
  → Decide whether to generate proactive reminder / suggestion / question
  → If yes → assemble proactive message via B1 → present in UI
```

Key constraints:
- Proactive reminder frequency must have a hard cap (e.g., max once per hour), and the user can disable it entirely.
- IdleThink reading local DB is not egress; privacy mode should not block it. However, if the user has disabled the "memory toggle", IdleThink must not access B2 memory.
- IdleThink proactive reminders that require external info via agent-toolbox (e.g., "monitor webpage price") must still go through A3 Consent.
- This does not conflict with "companion first" — proactive care is an advanced form of companionship, not harassment.

**Tiered degradation strategy**: Auto-selects IdleThink driving mode based on hardware capability, transparent to user.

| Mode | Hardware | Driver |
|------|----------|--------|
| High-tier | VRAM ≥8GB | LLM-driven IdleThink, full reasoning capability |
| Mid-tier | VRAM 4-6GB | Hybrid rule engine + lightweight LLM (e.g., Phi-3); rule engine handles common scenarios (typing 2h straight → break reminder), LLM handles complex judgment |
| Low-tier | VRAM <4GB | Rule engine only, no LLM calls. Rule engine based on predefined templates (time, activity duration, schedule matching), deterministic output |

### 6.10 C-layer JobScheduler (S8)

Background task scheduler managing long-running, scheduled, delayed, and event-listening tasks.

| Item | Consensus | Status |
|------|-----------|--------|
| Scheduled tasks | Cron-like, e.g., "backup data at 8 AM daily" | backlog |
| Delayed tasks | e.g., "remind me to attend meeting in 5 minutes" | backlog |
| Event-listening tasks | e.g., "monitor price changes on a webpage" | backlog |
| Long-running tasks | e.g., "download this 50GB file for me" | backlog |
| Skill integration | Skills register background tasks via standard API | backlog |
| Persistence | Task state persisted to SQLite, recoverable after Agent restart | backlog |
| Non-blocking UI | All background tasks async; notify UI via events (done/fail/progress) | backlog |
| Skill liveness check | Before triggering a task, check via skill_manager if target Skill is running; if stopped, mark task as failed and generate `source: TOOLBOX` error record | backlog |

### 6.10.1 Unified error code spec (S8)

Standardized error structure across A/B/C layers. Each error carries `source` (origin layer) and `recoverable` tags.

| Field | Description |
|-------|-------------|
| `code` | Unique error code, e.g. `E_SKILL_NETWORK_TIMEOUT` |
| `source` | Error origin layer: `A2` / `B3` / `B4` / `C1` / `SKILL` / `TOOLBOX` |
| `recoverable` | `true` / `false` |
| `user_message` | Localized message for the user |
| `dev_message` | Stack trace or context for the developer |

**Constraints**:
- Core modules (A/B/C): each module limited to 10-20 error codes. Error codes are for recovery logic, not logging — logs should use stack traces and context.
- Skill errors must include `error_code` field; otherwise invoker auto-wraps as `E_SKILL_UNHANDLED_ERROR`.

### 6.10.2 Circuit breaker (S8)

A2 invoker maintains `failure_count` per Skill. After N consecutive failures (default 3), auto-opens circuit; subsequent calls return `E_SKILL_CIRCUIT_OPEN` without actually invoking the Skill. Circuit auto-recovers to half-open probe after N minutes (default 5).

### 6.11 A2 AttentionAwareness (S9)

Attention awareness module alongside GoalManager, ensuring "proactive care" does not intrude on the user.

| Item | Consensus | Status |
|------|-----------|--------|
| Quiet period detection | Detect foreground app state via agent-toolbox (fullscreen? game? video call?); auto-lower reminder level during late night | backlog |
| Reminder tiers | ① Low: sidebar bubble or tray icon color change only; ② Medium: system native notification; ③ High: popup + sound (user-explicit urgent reminders only) | backlog |
| Output suppression | When user is busy, IdleThink reminders skip B1 assembly, write to pending queue, present when idle; suppression decision based on utility function — when user is active in code editor or mouse is stationary for long periods, low-utility reminders skip B1 assembly, only written to pending queue or degraded to tray icon blink | backlog |
| Privacy boundary | Requires explicit independent Consent on enable; dialog states "This mod needs to read your system activity state (e.g., fullscreen, typing) to determine if reminders are appropriate. No screen content is recorded or uploaded."; settings page provides independent toggle, disabling it does not affect other IdleThink capabilities | backlog |

### 6.13 A1 DevTools & Auto-Eval (S8)

Built-in developer tools and automated evaluation system.

| Item | Consensus | Status |
|------|-----------|--------|
| Developer mode | Desktop shell adds "Developer mode" toggle; sidebar gains "Message monitor" showing real-time JSON messages flowing through A/B/C layers | backlog |
| Skill drag-and-drop orchestration | In developer mode, users can drag-and-drop Skills on UI — connect "input → SkillA → SkillB → output" to create composite Skills | backlog |
| Auto-evaluation | `Evaluator` component: after each IdleThink or GoalManager decision, auto-records "expected result" vs "actual result", quantifying whether "proactive care becomes harassment" | backlog |

### 6.14 A2 Router LLM & Self-Reflection (S9)

LLM-driven intent routing and self-reflection capability.

| Item | Consensus | Status |
|------|-----------|--------|
| Router LLM | Introduce lightweight Router LLM (e.g., Phi-3) dedicated to judging user intent: chat (→ B1), lookup info (→ RAG), execute code (→ Toolbox). Replaces regex matching and keyword detection, handling fuzzy boundaries | backlog |
| Self-Reflection | At end of day or session, auto-call LLM to summarize today's conversation, generate N new `#remember` facts for B2. Write must follow write gate principle (`#remember` as sole channel); generated facts require user confirmation before storage | backlog |

### 6.12 A2 ResourceArbitrator (S9)

Multi-process resource arbiter preventing OOM when llama.cpp + Docker + Playwright run simultaneously.

| Item | Consensus | Status |
|------|-----------|--------|
| Foreground priority | When C1 generates long text, auto-pause `low_priority` background tasks in JobScheduler | backlog |
| Docker hard limits | agent-toolbox container set `--memory=512m --cpus=1` | backlog |
| Degradation strategy | When available memory drops below threshold (<500MB), auto-pause IdleThink; tray icon shows "resource constrained" | backlog |
| JobScheduler reservation | S8 JobScheduler tasks carry `priority` and `resource_requirement` fields | backlog |


---

## 7. Voice (Sprint 8)

TTS Skill `cosyvoice-tts` + Plugin `voice-output`; ASR Skill `asr-service` + Plugin `voice-input`.

---

## 7-B Multimodal interaction (future exploration · Sprint 10+)

| Direction | Form | Description |
|-----------|------|-------------|
| **Global overlay** | Plugin + agent-toolbox | Screen word lookup, instant translation via pywebview overlay, calling agent-toolbox for screen context |
| **Attention prediction** | AttentionAwareness extension | Predict user attention focus via mouse trajectory and window switching patterns; proactively offer context-relevant help in low-distraction scenarios (e.g., "Need me to summarize this webpage?"). Requires independent Consent; no screen content recorded or uploaded |

## 8. AgentScope notes

**Borrow (future)**

- A2 **Middleware onion chain**: sandbox → privacy → Skill routing (not current Sprint).
- **PermissionEngine tri-state**: Consent extension ALLOW / ASK / DENY.
- **Plan Mode**: PlanNotebook may reference AgentScope `PlanModeManager` interface.

**Moat (non-negotiable)**

1. B/C `check_imports` architecture-level network ban.
2. Transparent memory: `active/cancelled` + `memory_type` + habit conflict + decay.
3. **B4 polisher** as final output gate for all output.
4. Skill **independent process + localhost lock + API Key host injection**.
5. **agent-toolbox exoskeleton**: all "actions" executed in isolated Docker sandbox Skill, never polluting core process; A3 Consent gates every step.
6. **Proactive care has boundaries**: IdleThink hard frequency cap + user can disable; GoalManager does not overstep.

---

## 9. Gaps & responses

| Gap | Response | Priority | Sprint |
|-----|----------|----------|--------|
| Complex tasks unorchestrated | PlanOrchestrator + TaskContext | **High** | S9 |
| Long-term goals undriven | GoalManager + IdleThink | Medium | S9 |
| Background tasks unscheduled | JobScheduler | **High** | S8 |
| Proactive reminders may intrude | AttentionAwareness + reminder tiers | **High** | S9 |
| Multi-process resource contention risk | ResourceArbitrator + Docker hard limits | Medium | S9 |
| Error tracing difficult | ErrorCode Schema + circuit breaker | **High** | S8 |
| Vector vs SQLite inconsistency | Transaction log + reindex command | Low | S9+ |
| Skill dependency conflicts | venv isolation + manifest dependency declaration | Medium | S8 |
| Docker mandatory dependency friction | Native mode fallback + Consent prompt | Medium | S8 |
| Cross-extension coordination missing | Pipeline orchestrator | Low | S9+ |
| User profile passive | Passive profile layer | Low | S9+ |
| Security policy propagation | manifest CSP placeholder | Medium | 7.1 wrap-up |
| Memory long-term bloat risk | Hot-cold vector separation + archive strategy | Low | S9+ |
| Skill dependency supply chain risk | Hash locking + SBOM generation | Medium | S8 |
| Knowledge DB & memory index not connected | Hot-cold knowledge separation + RAG API-ization | Low | S9+ |
| Cross-layer communication format inconsistent | Unified Message Bus + BaseMessage Schema | Medium | S9 |
| Developer debugging tools limited | DevTools + message monitor + drag-and-drop orchestration | Medium | S8 |
| Intent routing relies on regex matching | Router LLM + Self-Reflection | Medium | S9 |
| Degradation paths lack test coverage | Degradation scenario test checklist + regression scripts | Medium | S8 |
| Brain-body communication latency | agent-toolbox async callback + result cache | Medium | S8 |

## 10. Sprint boundaries

### Closed

Sprint 0～6.8; **7.1 ✅** `skill_manager` registry/policy + wrap-up (`extensions/installed/`, `type` routing, CSP/error code placeholders).

### Sprint 7 (current)

| Item | Content | Status |
|------|---------|--------|
| 7.1 wrap-up | schema `error_codes`, `content_security_policy`; `type` field | backlog |
| 7.2 | Consent `purpose_type` + API Key host injection | backlog |
| 7.3 | **skill-market standalone repo** MVP API | backlog |
| 7.4 | novel-writer standalone Skill + local_api | backlog |
| 7.5 | `/skill` CLI + explicit routing | backlog |
| 7.6 | Evaluation + check_imports extension | partial |
| 7.7 | **agent-toolbox super Skill MVP** | Docker sandbox + Playwright + code execution (depends on 7.2 + 7.4) | backlog |

### Sprint 8

Plugin dynamic loader (`plugin_loader` + frontend PluginLoader); mod marketplace UI; extension error codes; CosyVoice + voice-output example; template repos; four core docs finalized; **JobScheduler** (background task scheduler, alongside Plugin loader); **ErrorCode Schema + circuit breaker**; **venv isolation + Native mode fallback**; **DevTools** (developer mode + message monitor + Skill drag-and-drop orchestration, alongside mod marketplace UI); **Hardware check** (downloader integrates hardware detection + tiered recommendation + honest prompt); **Built-in mods** (3 official Skills pre-listed: code interpreter / knowledge base assistant / life manager).

### Sprint 9A (Core skeleton)

Tool (`tool_registry` + tiers); **PlanOrchestrator + TaskContext** (alongside Pipeline); **PlanNotebook** (PlanOrchestrator frontend UI); **Message queue upgrade** (agent-toolbox ZeroMQ/nanomsg communication mode + A2 MessageRouter); **ResourceArbitrator**.

> 9A goal: First get complex task orchestration skeleton working — ensure PlanOrchestrator can correctly decompose, execute, and recover tasks.

### Sprint 9B (Soft capabilities)

**GoalManager + IdleThink loop** (prerequisite for passive profile); **AttentionAwareness**; **Router LLM + Self-Reflection**; desktop 2D character; **UI micro-interactions** (breathing light + execution animation + standby pose, alongside 2D character).

> 9B goal: After 9A skeleton is running, layer on proactive care and attention awareness soft capabilities, reducing debugging complexity.


---

## 11. Tech stack & data layout

| Area | Choice |
|------|--------|
| Language | Python 3.11 |
| Inference | llama-cpp-python + GGUF |
| Default model | Qwen2.5-1.5B-Instruct Q4_K_M |
| Storage | SQLite + FTS5 |
| Desktop | pywebview + pystray |
| Skill validation | `pip install -e ".[skill]"` |
| Hardware detection | Built into downloader/installer; detects GPU VRAM, system RAM, available disk |

**Not introducing**: torch, langchain, chromadb, faiss, Electron, npm build chain (Plugin also zero-build).

```text
{data_root}/
├── companion.db
├── knowledge.db
├── configs/
├── models/
├── extensions/installed/
│   ├── <skill-name>/
│   │   └── manifest.json
│   ├── <plugin-name>/
│   │   └── plugin.json
│   └── <tool-name>/
│       └── manifest.json
├── exports/
└── logs/
```

Ops: [`USER_MANUAL_v1.0_en.md`](./USER_MANUAL_v1.0_en.md).

---

**Authority**: Chinese `ARCHITECTURE_v2.0_zh.md` on ambiguity.
