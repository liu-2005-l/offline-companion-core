"""会话回复算术审计接入测试。"""

from __future__ import annotations

from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import Persona


class _ArithmeticBackend:
    """摘要：按队列返回回复并记录系统提示。"""

    def __init__(self, replies: list[str], *, streamed_reply: str | None = None) -> None:
        self.replies = list(replies)
        self.streamed_reply = streamed_reply
        self.system_prompts: list[str] = []

    def generate(self, **kwargs) -> str:
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        return self.replies.pop(0)

    def generate_stream(self, **kwargs):
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        yield str(self.streamed_reply or "")


def _core_and_conn(tmp_path):
    persona = Persona(
        persona_id="audit",
        name="audit",
        system_prompt="你是本地助手。",
        role_lock=True,
        memory_default_on=False,
        default_companion_display_name="助手",
        companion_display_name=None,
        raw={},
    )
    conn = connect(tmp_path / "arithmetic-session.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    return PersonaSessionCore(persona), conn


def test_sync_session_retries_wrong_arithmetic_with_system_feedback(tmp_path) -> None:
    core, conn = _core_and_conn(tmp_path)
    backend = _ArithmeticBackend(["Booth 计算可得 7×3=77。", "重新核算后 7×3=21。"])

    result = core.assemble_reply(
        backend,
        conn,
        user_message="按照 Booth 算法计算 7 乘 3",
        history=[],
        memory_enabled=False,
    )

    assert result.reply == "重新核算后 7×3=21。"
    assert len(backend.system_prompts) == 2
    assert "【算术校验反馈】" in backend.system_prompts[1]
    assert "正确值 21" in backend.system_prompts[1]


def test_stream_session_keeps_tokens_but_returns_audited_terminal_reply(tmp_path) -> None:
    core, conn = _core_and_conn(tmp_path)
    backend = _ArithmeticBackend(["重新核算后 7×3=21。"], streamed_reply="Booth 计算可得 7×3=77。")

    events = list(
        core.assemble_reply_stream(
            backend,
            conn,
            user_message="按照 Booth 算法计算 7 乘 3",
            history=[],
            memory_enabled=False,
        )
    )

    assert any(event.get("token") == "Booth 计算可得 7×3=77。" for event in events)
    assert events[-1]["reply"] == "重新核算后 7×3=21。"


def test_session_without_assertion_does_not_retry(tmp_path) -> None:
    core, conn = _core_and_conn(tmp_path)
    backend = _ArithmeticBackend(["这是普通回复。"])

    result = core.assemble_reply(
        backend,
        conn,
        user_message="你好",
        history=[],
        memory_enabled=False,
    )

    assert result.reply == "这是普通回复。"
    assert len(backend.system_prompts) == 1


def test_session_retries_copular_arithmetic_statement(tmp_path) -> None:
    """摘要：会话路径识别“结果是”系动词断言并反馈正确值。"""

    core, conn = _core_and_conn(tmp_path)
    backend = _ArithmeticBackend(["3乘7的结果是14。", "重新核算后，3乘7的结果是21。"])

    result = core.assemble_reply(
        backend,
        conn,
        user_message="算一下 3 乘 7",
        history=[],
        memory_enabled=False,
    )

    assert result.reply == "重新核算后，3乘7的结果是21。"
    assert "正确值 21" in backend.system_prompts[-1]
