"""cli：终端 UI 宿主入口（A1；单轮编排委托 conversation_orchestrator）。"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from offline_companion.core.memory_lifecycle.drafts import (
    confirm_draft,
    create_draft_from_session,
    discard_draft,
    list_pending_drafts,
)
from offline_companion.core.memory_lifecycle.manager import (
    MemoryLifecycleManager,
    apply_bundle_import,
    prepare_export_bundle,
)
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import (
    apply_companion_display_name,
    load_persona_file,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.runtime.inference_backend import (
    EchoBackend,
    create_llama_backend,
    try_stderr_cuda_hint,
)
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.runtime.storage_index.export_import import read_bundle_archive, write_bundle_archive
from offline_companion.shared.types import AppPaths, OutboundPlan, OutboundScope, PrivacyMode
from offline_companion.shell.outbound_manager.consent import persist_consent_artifact
from offline_companion.shell.outbound_manager.connector import post_cloud_completion
from offline_companion.shell.policy_engine.engine import ensure_outbound_allowed
from offline_companion.shell.policy_engine.rules import default_app_paths
from offline_companion.core.knowledge_rag.config import load_knowledge_config
from offline_companion.runtime.storage_index.knowledge_store import (
    connect_knowledge,
    default_knowledge_db_path,
)
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.knowledge_turn import run_knowledge_search


def _parse_privacy(s: str) -> PrivacyMode:
    return PrivacyMode(s)


def _help_text() -> str:
    return (
        "/quit            Exit\n"
        "/memory on|off   Toggle retrieval + #remember captures\n"
        "/memory list     List recent memory rows\n"
        "/memory del ID   Delete a memory row\n"
        "/memory set ID text — Update body\n"
        "/memory drafts   List pending summary drafts\n"
        "/memory confirm ID — Promote draft to formal memory\n"
        "/memory discard ID — Drop draft without saving\n"
        "/summarize        Build rule-based summary draft (not saved until confirm)\n"
        "/export PATH.zip Write portable bundle (manifest + jsonl)\n"
        "/import PATH.zip Import bundle with new session ids\n"
        "/cloud-demo      Exercise outbound consent gate (no network I/O)\n"
        "/cloud-reason Q  Cloud assist (consent + A3 + B4; stub if env set)\n"
        "/search-knowledge Q  Local knowledge FTS (B3 gate; snippets only by default)\n"
    )


def _render_turn_result(result) -> None:
    """摘要：将编排结果打印到终端。"""
    if result.memory_saved:
        print("(saved memory:", "; ".join(result.memory_saved), ")")
    if result.memory_skipped_trigger:
        print("(memory save skipped: on_explicit_save trigger is OFF)")
    if result.memory_explanation:
        expl = result.memory_explanation
        print("(记忆召回", expl["count"], "条)")
        for item in expl["matched"]:
            print(f"  #{item['memory_id']}: {item['matched_on'].get('summary', '')}")
    if result.cloud_degraded:
        print("(云端润色不可用，已用本地陪伴方式回答)")
    elif result.cloud_used:
        print("(本轮经云端增强，已润色)")
    if result.reply is not None:
        print("Bot>", result.reply)


def cmd_chat(args: argparse.Namespace) -> int:
    """摘要：启动本地 REPL 会话。"""
    paths = default_app_paths()
    if args.data_dir:
        root = Path(args.data_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        paths = AppPaths(
            root=root,
            db_path=root / "companion.db",
            personas_dir=root / "personas",
            exports_dir=root / "exports",
        )
        paths.personas_dir.mkdir(parents=True, exist_ok=True)
        paths.exports_dir.mkdir(parents=True, exist_ok=True)

    persona_path = Path(args.persona).expanduser()
    persona = load_persona_file(persona_path)
    if getattr(args, "companion_name", None):
        persona = apply_companion_display_name(persona, args.companion_name)
    session_core = PersonaSessionCore(persona)
    privacy = _parse_privacy(args.privacy)
    triggers = load_triggers()

    memory_on = persona.memory_default_on if args.memory is None else bool(args.memory)

    conn = connect(paths.db_path)
    session_id = args.session_id or str(uuid.uuid4())
    row = conn.execute("SELECT id FROM sessions WHERE id = ?;", (session_id,)).fetchone()
    if not row:
        new_session(conn, session_id, persona.persona_id, title=args.title)

    if args.model:
        try_stderr_cuda_hint()
        try:
            backend = create_llama_backend(
                args.model,
                n_ctx=args.n_ctx,
                n_gpu_layers=args.n_gpu_layers,
                run_health_check=True,
            )
        except InferenceBackendError as e:
            print("推理后端初始化失败:", e, file=sys.stderr)
            return 1
        print("推理:", backend.health_check().message)
    else:
        backend = EchoBackend("no-model")

    orchestrator = ConversationOrchestrator(
        session_core=session_core,
        backend=backend,
        conn=conn,
        session_id=session_id,
        triggers=triggers,
        history_limit=args.history,
        max_tokens=args.max_tokens,
    )

    knowledge_cfg = load_knowledge_config()
    knowledge_db_path = knowledge_cfg.db_path or default_knowledge_db_path(paths.root)
    knowledge_conn = connect_knowledge(knowledge_db_path)

    print("Session:", session_id)
    print("Privacy:", privacy.value, "| Memory:", "on" if memory_on else "off")
    print("Commands: /help /quit /memory … /export /import /cloud-demo")
    print("Tip: prefix a line with `#remember ...` to add memory without extra UI.")
    print("Knowledge DB:", knowledge_db_path, "| plugin enabled:", knowledge_cfg.enabled, "\n")

    while True:
        try:
            user = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not user:
            continue

        if user.startswith("/search-knowledge"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /search-knowledge <query>")
                continue
            if not knowledge_cfg.enabled:
                print("Knowledge plugin is disabled (configs/knowledge/default.yaml enabled: false).")
                continue
            q = parts[1].strip()
            kr = run_knowledge_search(
                query=q,
                config=knowledge_cfg,
                knowledge_conn=knowledge_conn,
                companion_conn=conn,
                session_id=session_id,
                persona=persona,
                session_core=session_core,
                backend=backend,
                memory_on=memory_on,
            )
            if kr.blocked_by_safety:
                print("Bot>", kr.safety_reply)
                continue
            print(kr.snippet_display)
            if kr.answer_after_search and kr.reply:
                print("Bot>", kr.reply)
            continue

        if user.startswith("/cloud-reason"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /cloud-reason <your question>")
                continue
            question = parts[1].strip()
            plan = OutboundPlan(
                payload_excerpt=f"user: {question[:500]}",
                will_send=["Current user question only"],
                will_not_send=[
                    "Full chat history",
                    "Memory database contents",
                    "Persona YAML file",
                ],
                purpose="Cloud reasoning assist for current question",
                scope=OutboundScope.THIS_TURN,
            )
            try:
                ensure_outbound_allowed(privacy, plan)
                artifact = {
                    "request_id": str(uuid.uuid4()),
                    "scope": plan.scope.value,
                    "purpose": plan.purpose,
                    "user_decision": "allowed",
                    "timestamp": time.time(),
                    "data_category": "cloud_reason",
                    "hash_of_uploaded_content": None,
                }
                persist_consent_artifact(conn, artifact)
                turn = orchestrator.run_cloud_turn(
                    question,
                    purpose=plan.purpose,
                    memory_on=memory_on,
                    cloud_post=post_cloud_completion,
                )
                memory_on = turn.memory_on
                _render_turn_result(turn)
            except Exception as e:
                print("Blocked or failed:", e)
            continue

        if user.startswith("/"):
            handled, memory_on = _handle_slash_command(
                user,
                memory_on=memory_on,
                conn=conn,
                session_id=session_id,
                persona=persona,
                privacy=privacy,
            )
            if handled:
                continue
            print("Unknown command. Try /help")
            continue

        turn = orchestrator.run_turn(user, memory_on=memory_on)
        memory_on = turn.memory_on
        _render_turn_result(turn)

    return 0


def _handle_slash_command(
    user: str,
    *,
    memory_on: bool,
    conn,
    session_id: str,
    persona,
    privacy: PrivacyMode,
) -> tuple[bool, bool]:
    if user in ("/quit", "/exit"):
        raise SystemExit(0)

    if user == "/help":
        print(_help_text())
        return True, memory_on

    if user == "/summarize":
        draft = create_draft_from_session(conn, session_id)
        print(draft.body)
        print(f"\n[草稿 id={draft.id}] 确认: /memory confirm {draft.id}  丢弃: /memory discard {draft.id}")
        return True, memory_on

    if user.startswith("/memory"):
        parts = user.split(maxsplit=3)
        if len(parts) < 2:
            print("Usage: /memory on|off|list|drafts|confirm <id>|discard <id>|del <id>|set <id> <text>")
            return True, memory_on
        sub = parts[1].lower()
        if sub == "on":
            print("Memory writes + retrieval: ON")
            return True, True
        if sub == "off":
            print("Memory writes + retrieval: OFF")
            return True, False
        if sub == "list":
            for h in MemoryLifecycleManager.list_recent_memory(conn, limit=30):
                print(f"{h.id}: {h.body}")
            return True, memory_on
        if sub == "drafts":
            drafts = list_pending_drafts(conn, session_id)
            if not drafts:
                print("No pending drafts.")
            for d in drafts:
                preview = d.body.replace("\n", " ")[:100]
                print(f"draft {d.id}: {preview}…")
            return True, memory_on
        if sub == "confirm":
            if len(parts) != 3:
                print("Usage: /memory confirm <draft_id>")
                return True, memory_on
            mid = confirm_draft(conn, int(parts[2]))
            if mid:
                print(f"Saved as memory chunk id={mid}.")
            else:
                print("Draft not found or not pending.")
            return True, memory_on
        if sub == "discard":
            if len(parts) != 3:
                print("Usage: /memory discard <draft_id>")
                return True, memory_on
            if discard_draft(conn, int(parts[2])):
                print("Draft discarded.")
            else:
                print("Draft not found or not pending.")
            return True, memory_on
        if sub == "del":
            if len(parts) != 3:
                print("Usage: /memory del <id>")
                return True, memory_on
            if MemoryLifecycleManager.delete_memory_chunk(conn, int(parts[2])):
                print("Deleted.")
            else:
                print("Not found.")
            return True, memory_on
        if sub == "set":
            if len(parts) != 3 or " " not in parts[2]:
                print("Usage: /memory set <id> <new text>")
                return True, memory_on
            mid, text = parts[2].split(" ", 1)
            if MemoryLifecycleManager.update_memory_chunk(conn, int(mid), text):
                print("Updated.")
            else:
                print("Not found or empty.")
            return True, memory_on

        print("Usage: /memory on|off|list|drafts|confirm <id>|discard <id>|del <id>|set <id> <text>")
        return True, memory_on

    if user.startswith("/export"):
        parts = user.split(maxsplit=1)
        if len(parts) != 2:
            print("Usage: /export PATH.zip")
            return True, memory_on
        out = Path(parts[1].strip().strip('"'))
        snap = dict(persona.raw)
        snap["resolved_id"] = persona.persona_id
        payload = prepare_export_bundle(conn, persona_snapshot=snap)
        write_bundle_archive(payload, out)
        print("Wrote", out.resolve())
        return True, memory_on

    if user.startswith("/import"):
        parts = user.split(maxsplit=1)
        if len(parts) != 2:
            print("Usage: /import PATH.zip")
            return True, memory_on
        z = Path(parts[1].strip().strip('"'))
        payload = read_bundle_archive(z)
        summary = apply_bundle_import(conn, payload)
        print("Imported sessions:", summary["imported_sessions"])
        return True, memory_on

    if user.startswith("/cloud-demo"):
        plan = OutboundPlan(
            payload_excerpt="user: demo outbound",
            will_send=["Current user line only (demo)"],
            will_not_send=[
                "Past session messages (not sent in this demo)",
                "Memory database (not sent)",
                "Persona file (not sent)",
            ],
            purpose="Demonstrate consent gate (no HTTP request is made)",
            scope=OutboundScope.THIS_TURN,
        )
        try:
            ensure_outbound_allowed(privacy, plan)
            artifact = {
                "request_id": str(uuid.uuid4()),
                "scope": plan.scope.value,
                "purpose": plan.purpose,
                "user_decision": "allowed_demo",
                "timestamp": time.time(),
                "data_category": "demo",
                "hash_of_uploaded_content": None,
            }
            persist_consent_artifact(conn, artifact)
            print("OK: outbound would proceed (demo only — no call executed). Consent recorded.")
        except Exception as e:
            print("Blocked:", e)
        return True, memory_on

    return False, memory_on


def _default_persona_path() -> str:
    """摘要：默认 persona YAML（便携模式可读环境变量覆盖）。"""
    env = os.environ.get("OFFLINE_COMPANION_PERSONA_PATH")
    if env:
        return env
    return str(Path("configs") / "personas" / "default.yaml")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="companion")
    sub = p.add_subparsers(dest="cmd", required=True)

    chat = sub.add_parser("chat", help="Run local REPL")
    chat.add_argument(
        "--persona",
        type=str,
        default=_default_persona_path(),
    )
    chat.add_argument("--session-id", type=str, default=None)
    chat.add_argument("--title", type=str, default=None)
    chat.add_argument(
        "--privacy",
        type=str,
        default=PrivacyMode.LOCAL_ONLY.value,
        choices=[m.value for m in PrivacyMode],
    )
    chat.add_argument(
        "--memory",
        type=int,
        default=None,
        help="1=on 0=off; omit to use persona default",
    )
    chat.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to .gguf (optional; echo mode if omitted)",
    )
    chat.add_argument("--n-ctx", type=int, default=2048)
    chat.add_argument("--n-gpu-layers", type=int, default=0)
    chat.add_argument(
        "--probe-generate",
        action="store_true",
        help="启动时对模型做一次极短 generate 探测（更慢）",
    )
    chat.add_argument("--history", type=int, default=30)
    chat.add_argument("--max-tokens", type=int, default=256)
    chat.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Override user data root for dev/tests",
    )
    chat.add_argument(
        "--companion-name",
        type=str,
        default=None,
        help="用户为陪伴指定的自称（等同注册页昵称）；省略则用 default_companion_display_name",
    )

    sub.add_parser("version", help="Print version")

    check = sub.add_parser("check-model", help="检查 GGUF 模型与 llama-cpp 是否可用")
    check.add_argument("--model", type=str, required=True, help="Path to .gguf")
    check.add_argument("--n-ctx", type=int, default=512)
    check.add_argument("--n-gpu-layers", type=int, default=0)
    check.add_argument(
        "--probe-generate",
        action="store_true",
        help="额外执行极短 generate 探测",
    )

    return p


def main(argv: list[str] | None = None) -> None:
    """摘要：CLI 入口。"""
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "version":
        from offline_companion import __version__

        print(__version__)
        raise SystemExit(0)
    if args.cmd == "check-model":
        from offline_companion.runtime.inference_backend import LlamaCppBackend

        report = LlamaCppBackend.check_model(
            args.model,
            n_ctx=args.n_ctx,
            n_gpu_layers=args.n_gpu_layers,
            load_model=True,
            probe_generate=args.probe_generate,
        )
        print(report.message)
        raise SystemExit(0 if report.ok else 1)
    if args.cmd == "chat":
        mem = None if args.memory is None else bool(args.memory)
        ns = argparse.Namespace(**{**vars(args), "memory": mem})
        raise SystemExit(cmd_chat(ns))
    parser.error("Unknown command")


if __name__ == "__main__":
    main()
