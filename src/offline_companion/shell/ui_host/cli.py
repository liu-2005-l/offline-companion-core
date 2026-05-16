"""cli：终端 UI 宿主入口（A1；编排 A2/B/C 以满足宪章依赖方向）。"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

from offline_companion.core.memory_lifecycle.manager import (
    MemoryLifecycleManager,
    apply_bundle_import,
    prepare_export_bundle,
)
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.runtime.inference_backend import (
    EchoBackend,
    create_llama_backend,
    try_stderr_cuda_hint,
)
from offline_companion.runtime.storage_index.engine import append_message, connect, new_session, recent_messages
from offline_companion.runtime.storage_index.export_import import read_bundle_archive, write_bundle_archive
from offline_companion.shared.types import AppPaths, OutboundPlan, OutboundScope, PrivacyMode
from offline_companion.shell.outbound_manager.consent import persist_consent_artifact
from offline_companion.shell.policy_engine.engine import ensure_outbound_allowed
from offline_companion.shell.policy_engine.rules import default_app_paths


def _parse_privacy(s: str) -> PrivacyMode:
    return PrivacyMode(s)


def _help_text() -> str:
    return (
        "/quit            Exit\n"
        "/memory on|off   Toggle retrieval + #remember captures\n"
        "/memory list     List recent memory rows\n"
        "/memory del ID   Delete a memory row\n"
        "/memory set ID text — Update body\n"
        "/export PATH.zip Write portable bundle (manifest + jsonl)\n"
        "/import PATH.zip Import bundle with new session ids\n"
        "/cloud-demo      Exercise outbound consent gate (no network I/O)\n"
    )


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
    privacy = _parse_privacy(args.privacy)

    if args.memory is None:
        memory_on = persona.memory_default_on
    else:
        memory_on = bool(args.memory)

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
        report = backend.health_check()
        print("推理:", report.message)
    else:
        backend = EchoBackend("no-model")

    print("Session:", session_id)
    print("Privacy:", privacy.value, "| Memory:", "on" if memory_on else "off")
    print("Commands: /help /quit /memory … /export /import /cloud-demo")
    print("Tip: prefix a line with `#remember ...` to add memory without extra UI.\n")

    history_limit = args.history

    while True:
        try:
            user = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not user:
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

        safety = classify_user_text(user)
        if safety.tier != SafetyTier.OK:
            assert safety.user_visible_reply
            append_message(conn, session_id, "user", user, meta={"safety": safety.tier.value})
            append_message(
                conn,
                session_id,
                "assistant",
                safety.user_visible_reply,
                meta={"safety": "fixed_reply"},
            )
            print("Bot>", safety.user_visible_reply)
            continue

        chat_text, mem_lines = MemoryLifecycleManager.maybe_extract_memory_commands(user)
        if memory_on and mem_lines:
            for m in mem_lines:
                MemoryLifecycleManager.add_memory_chunk(
                    conn, m, session_id=session_id, source="user_hash_command"
                )
            print("(saved memory:", "; ".join(mem_lines), ")")

        if not chat_text:
            continue

        append_message(conn, session_id, "user", chat_text)

        mem_block = ""
        if memory_on:
            hits = MemoryLifecycleManager.search_memory(conn, chat_text, limit=8)
            mem_block = MemoryLifecycleManager.format_memory_block(hits)

        hist = recent_messages(conn, session_id, limit=history_limit)
        hist_for_model = hist[:-1] if hist and hist[-1].role == "user" else hist

        reply = backend.generate(
            system_prompt=persona.system_prompt,
            history=hist_for_model,
            user_message=chat_text,
            memory_block=mem_block,
            max_tokens=args.max_tokens,
        )
        append_message(conn, session_id, "assistant", reply, meta={})
        print("Bot>", reply)

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

    if user.startswith("/memory"):
        parts = user.split(maxsplit=2)
        if len(parts) < 2:
            print("Usage: /memory on|off|list|del <id>|set <id> <text>")
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

        print("Usage: /memory on|off|list|del <id>|set <id> <text>")
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="companion")
    sub = p.add_subparsers(dest="cmd", required=True)

    chat = sub.add_parser("chat", help="Run local REPL")
    chat.add_argument(
        "--persona",
        type=str,
        default=str(Path("configs") / "personas" / "default.yaml"),
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
