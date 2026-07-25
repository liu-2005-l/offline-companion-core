#!/usr/bin/env python3
"""摘要：云端 Stub 黑盒验收入口。

说明：
- 该脚本用于 full_acceptance.py 调用，避免把云端链路逻辑塞进大验收脚本。
- 通过独立子进程运行，尽量减少全局副作用。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _configure_stdio_utf8() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _configure_stdio_utf8()
    os.environ.setdefault("OFFLINE_COMPANION_CLOUD_STUB", "1")
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    from offline_companion.core.memory_lifecycle.triggers import load_triggers
    from offline_companion.core.persona_session.persona_loader import load_persona_file
    from offline_companion.core.persona_session.session import PersonaSessionCore
    from offline_companion.runtime.inference_backend.mock import EchoBackend
    from offline_companion.runtime.storage_index.engine import connect, new_session
    from offline_companion.shell.outbound_manager.connector import post_cloud_completion
    from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator

    persona = load_persona_file(ROOT / "configs/personas/default.yaml")
    with tempfile.TemporaryDirectory(prefix="oc_cloud_smoke_") as td:
        db_path = Path(td) / "cloud.db"
        conn = connect(db_path)
        try:
            new_session(conn, "s1", persona.persona_id, title="cloud_smoke")
            orch = ConversationOrchestrator(
                session_core=PersonaSessionCore(persona),
                backend=EchoBackend("cloud_smoke"),
                conn=conn,
                session_id="s1",
                triggers=load_triggers(),
            )
            turn = orch.run_cloud_turn(
                "最近压力很大怎么办？",
                purpose="cloud_smoke",
                memory_on=False,
                cloud_post=post_cloud_completion,
            )
        finally:
            conn.close()
    if not turn.reply:
        print("[FAIL] 云端 Stub：无回复", file=sys.stderr)
        return 1
    if turn.cloud_degraded:
        print("[FAIL] 云端 Stub：不应降级", file=sys.stderr)
        return 1
    print("[PASS] 云端 Stub + B4 润色")
    print("       预览:", (turn.reply or "").replace("\n", " ")[:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
