"""摘要：B2 触发器 YAML 加载与开关（Sprint 1）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from offline_companion.core.memory_lifecycle.triggers import (
    TRIGGER_ON_EXPLICIT_SAVE,
    TRIGGER_ON_SUMMARIZE_REQUEST,
    is_enabled,
    load_triggers,
    maybe_summarize_to_memory,
)
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator


def test_load_default_triggers() -> None:
    reg = load_triggers()
    assert is_enabled(reg, TRIGGER_ON_EXPLICIT_SAVE)
    assert not is_enabled(reg, TRIGGER_ON_SUMMARIZE_REQUEST)


def test_explicit_save_disabled_skips_write(tmp_path) -> None:
    cfg = tmp_path / "triggers_off.yaml"
    cfg.write_text(
        yaml.dump(
            {
                "version": 1,
                "triggers": {
                    "on_explicit_save": {"enabled": False},
                    "on_summarize_request": {"enabled": False},
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    reg = load_triggers(cfg)
    conn = connect(tmp_path / "t.db")
    new_session(conn, "s1", "default", title=None)
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    orch = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("t"),
        conn=conn,
        session_id="s1",
        triggers=reg,
    )
    result = orch.run_turn("#remember 测试记忆", memory_on=True)
    assert result.memory_skipped_trigger
    assert not result.memory_saved
    row = conn.execute("SELECT COUNT(*) AS c FROM memory_chunks;").fetchone()
    assert int(row["c"]) == 0


def test_summarize_hook_returns_none_when_disabled() -> None:
    reg = load_triggers()
    assert maybe_summarize_to_memory("请总结一下", reg) is None
