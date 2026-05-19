"""摘要：云端单轮编排与硬降级（Sprint 2）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.local_reformatter.rule_reformatter import LOCAL_FALLBACK_PREFIX
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.errors import ReformatError
from offline_companion.shared.types import CloudCompletionResponse
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator


def _orch(tmp_path):
    conn = connect(tmp_path / "c.db")
    persona = load_persona_file(
        Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    )
    new_session(conn, "s1", persona.persona_id, title=None)
    return (
        ConversationOrchestrator(
            session_core=PersonaSessionCore(persona),
            backend=EchoBackend("test"),
            conn=conn,
            session_id="s1",
            triggers=load_triggers(),
        ),
        conn,
    )


def test_cloud_turn_success_with_reformat(tmp_path) -> None:
    orch, _conn = _orch(tmp_path)

    def fake_post(req):
        return CloudCompletionResponse(
            text="This is English from cloud.",
            raw={"test": True},
        )

    turn = orch.run_cloud_turn(
        "帮我减压",
        purpose="test",
        memory_on=False,
        cloud_post=fake_post,
    )
    assert turn.cloud_used
    assert not turn.cloud_degraded
    assert turn.reply
    assert "整理" in turn.reply or "呢" in turn.reply or "吧" in turn.reply


def test_cloud_turn_degrades_on_reformat_error(tmp_path) -> None:
    orch, _conn = _orch(tmp_path)

    def fake_post(req):
        return CloudCompletionResponse(text="raw cloud", raw={})

    with patch(
        "offline_companion.shell.ui_host.conversation_orchestrator.reformat_cloud_reply",
        side_effect=ReformatError("fail"),
    ):
        turn = orch.run_cloud_turn(
            "你好",
            purpose="test",
            memory_on=False,
            cloud_post=fake_post,
        )
    assert turn.cloud_degraded
    assert turn.reply.startswith(LOCAL_FALLBACK_PREFIX)
