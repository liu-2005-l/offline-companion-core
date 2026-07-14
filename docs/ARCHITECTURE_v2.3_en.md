# Offline Companion · Architecture & Development Notes v2.3 (English · Authoritative)

> **Version**: v2.3 · **Date**: 2026-06-30 (security closure revision)
> **Historical baseline**: [`architecture_v1.0.md`](./architecture_v1.0.md) (read-only; this document wins on conflicts)
> **Chinese**: [`ARCHITECTURE_v2.3_zh.md`](./ARCHITECTURE_v2.3_zh.md)

> **Extension development**: [`SKILL_DEV_GUIDE`](./SKILL_DEV_GUIDE_v1.0_en.md) · [`PLUGIN_DEV_GUIDE`](./PLUGIN_DEV_GUIDE_v1.0_en.md)
> **User manual**: [`USER_MANUAL`](./USER_MANUAL_v1.0_en.md)
> **Temporary next steps**: [`_TEMP_NEXT_STEPS_2026-06-12.md`](./_TEMP_NEXT_STEPS_2026-06-12.md)

## 1. Core principles

1. **Companionship first**: persona lock remains stable; output is assembled by B1 and gated by B4 as the final barrier.
2. **Extensions are secondary**: Skills / Plugins / Tools must not pollute the main path latency or trust boundary.
3. **Transparent memory**: editable, exportable, explainable recall (`matched_on`); `active/cancelled` lifecycle.
4. **Privacy first**: local by default; no silent cloud calls; `check_imports` hard-blocks network libraries.
5. **Auditable outbound**: A2 permission + A3 Consent Artifact.
6. **Hard requirements are equal**: safety wording, evaluation, export, and features share the same priority.
7. **Mind/body separation**: the agent core (B/C + A2 orchestration) handles task understanding, planning, and decomposition; execution is delegated to an isolated Skill sandbox (agent-toolbox), separating the “mind” from the “body”.

## 2. System layering (agent core)

| Layer | Package path | Modules | Network |
|------|--------------|---------|---------|
| **A Strategy Shell** | `shell/` | A1 UI, A2 policy, A3 outbound | A3 only |
| **B Companion Core** | `core/` | B1 persona session, B2 memory, B3 safety, B4 polish | Forbidden |
| **C Compute IO** | `runtime/` | C1 inference, C2 storage (vector writes first land in SQLite `vector_queue` WAL log, then the background asynchronously updates indexes; when the embedding model changes, provide a reindex command to rebuild vectors) | Forbidden |
| **Cross-cutting** | `shared/` | DTO / exceptions | — |

**Dependencies**: `A1→A2→B→C`; forbid `B→A`, `C→A`, `C→B`.  
**A1/A2 communication is fixed**: the desktop shell and A2 core communicate exclusively through the local HTTP API (127.0.0.1); no cross-process direct function calls.  
**B/C** may not import network libraries; whitelist: `shell/outbound_manager/connector.py`.  
**B/C do not know UI details or Skill/Plugin/Tool loading details** (extension orchestration lives only in A).  
**B/C communicate with A through the unified message protocol**, only sending/receiving standardized messages (`BaseMessage`), regardless of whether the transport underneath is function calls, HTTP, or queues. Message structure remains consistent across layers (`role`, `content`, `meta`, `timestamp`). `content` currently supports `text`, while `image_url` / `audio_buffer` are protocol placeholders for future multimodal Skills.

**Protocol is unified, implementation is chosen as needed**:
- **Main conversation path**: synchronous implementation (function-call simulation) for low latency and debuggability
- **Background task path**: asynchronous implementation (ZeroMQ queue), never blocking the main conversation

BaseMessage schema and the message bus abstraction live in `shared/`; all layers may depend on them. A layer owns `MessageRouter` and the transport layer, while B/C only speak to the interfaces in `shared/` and remain unaware of whether the transport is synchronous or asynchronous.

**Already delivered foundations**:
- `BaseMessage` unified protocol + synchronous `MessageRouter` minimal routing skeleton
- `StateManager` basic three-domain wrapper (`session` / `task` / `system`)
- `runtime_sandbox` minimal runtime danger-capability fallback
- `SkillInvoker` basic circuit breaker (failure count + circuit-open blocking)
- `check_imports` AST layering gate + direct execution entrypoint fix
- cross-platform path / encoding / test fixture compatibility fixes

## 3. Message bus engineering conventions

| Convention | Description |
|-----------|-------------|
| Default timeout | 30s, return `E_MESSAGE_TIMEOUT` on timeout |
| Retry | At most 1 retry; before retry, check whether `idempotency_key` has already executed |
| Exception propagation | Through BaseMessage `error` field; serialization uses JSON |
| Write idempotency | All write messages must carry a unique `idempotency_key`; `MessageRouter` checks execution records before running. Duplicate keys return the existing result and do not execute again |
| Session-level serialization | All messages in the same session execute strictly in order; no concurrency. Cross-session messages may run in parallel |
| Dead-letter queue | All failed messages go to a dead-letter queue, persisted in SQLite, with a manual compensation entry (CLI or settings page) |
| Async only for background tasks | JobScheduler and agent-toolbox background tasks may use async queues. The core conversation path stays synchronous |
| Dual-queue physical separation | Each session has two queues: a main conversation queue (high priority, strictly serialized) + a background task queue (low priority, parallelizable). Background tasks must never block the conversation response |
| Background priority | The background task queue cooperates with `ResourceArbitrator`: when resources are tight, low-priority background tasks pause first; high-priority tasks remain |
| Conflict priority | Main conversation state operations always outrank background tasks; on conflict, background tasks retry 3 times, then go to dead-letter, never blocking the main conversation |

**A-layer semantic wrapping**: all concrete Skill/Tool function names, parameter names, and API details are assembled in A layer and injected into the message as capability descriptions. B-layer system prompts must only contain persona descriptions and safety rules, and must never mention concrete tool names or business fields. Adding a new Skill should only require A-layer config changes; B-layer code stays untouched. Semantic conversion must include reverse similarity validation; parse failures should ask the user for missing information rather than guessing.

**CI checks**: CI adds prompt keyword scanning; B-layer prompt templates must not contain Skill names, function names, or parameter fields. Any hit fails the build. Add an integration test: a new Skill must work without modifying any B-layer code.

## 4. Single-turn companionship path

```text
User input → B3 safety (block → fixed reply)
         → [S8+] A2 dynamic sandbox / session interval
         → B2 recall (memory on; active only)
         → B1 assemble_reply → [S8+] context compression (async)
         → C1 generate → B4 → persist

> **Cloud model routing branch**: if AutoRouter decides to use a cloud model, generation goes through an A3 outbound call to a cloud inference Skill; after it returns, B4 still gates the result. Under LOCAL_ONLY mode, the original pure local path remains unchanged.
```

## 5. Complex task path

```text
User complex goal → A2 PlanOrchestrator
  ├─ task decomposition: split the goal into an ordered step sequence (Step 1 → Step 2 → Step 3)
  ├─ dependency management: declare inter-step data dependencies (Step 2 needs Step 1 output)
  ├─ state tracking: step status (pending / running / done / failed)
  ├─ error recovery: retry strategy or fallback path on step failure
  └─ context propagation: create a dedicated TaskContext for each task to store intermediate results
```

TaskContext is temporary and bound to a task; during Skill execution it can be read/written, and after completion key results may optionally be persisted to B2 memory (`#remember`), while the rest is discarded. PlanOrchestrator still goes through A3 Consent when calling Skills, Skills still run in isolated processes, and B/C do not perceive the existence of the plan.

## 6. Skills / Plugins / Tools strict split

> **Distinguishing axis**: what is modified → loading path → security model → audit path.

| Type | Position | Modified object | Runtime location | Security policy | Audit |
|------|----------|-----------------|------------------|-----------------|-------|
| **Skill** | Capability extension | What the agent **can do** | Isolated process (localhost API) | Process sandbox + Consent | **A3** |
| **Plugin** | UX enhancement | The agent **interaction form** (UI) | Desktop shell WebView (JS/CSS) | CSP + bridge constraints | **Frontend logs** |
| **Tool** | Lightweight function set | What the agent **can call** | In-process Python | builtin / certified / external | **A2 three-state** |

...