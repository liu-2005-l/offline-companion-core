from __future__ import annotations

from offline_companion.core.persona_session.expression import (
    IDENTITY_REMINDER_HEADER,
    IDENTITY_RETRY_REMINDER_HEADER,
    STYLE_BLOCK_HEADER,
    PersonaExpressionConfig,
    detect_identity_cliff,
    is_identity_intent,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session, recent_messages
from offline_companion.shared.types import MessageRow, Persona


def _persona(*, style_examples: list[dict[str, str]] | None = None) -> Persona:
    raw: dict[str, object] = {"persona_descriptor": "温和、带一点俏皮"}
    if style_examples is not None:
        raw["style_examples"] = style_examples
    return Persona(
        persona_id="w2",
        name="w2",
        system_prompt="你是一个本地陪伴助手。",
        role_lock=True,
        memory_default_on=True,
        default_companion_display_name="助手一号",
        companion_display_name=None,
        raw=raw,
    )


class CaptureBackend:
    def __init__(self, replies: list[str] | None = None) -> None:
        self.system_prompts: list[str] = []
        self.user_messages: list[str] = []
        self.replies = list(replies or ["ok"])

    def generate(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> str:
        del history, memory_block, max_tokens
        self.system_prompts.append(system_prompt)
        self.user_messages.append(user_message)
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]


def test_arm_a_injects_style_examples_when_present(tmp_path) -> None:
    """摘要：臂 A 从 persona.raw 注入风格锚点，防止假臂开跑。"""
    persona = _persona(
        style_examples=[
            {"user": "今天好累", "assistant": "累就先歇一会儿吧。"},
        ]
    )
    core = PersonaSessionCore(persona)
    conn = connect(tmp_path / "a.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    backend = CaptureBackend()

    result = core.assemble_reply(
        backend,
        conn,
        user_message="随便聊聊",
        history=[],
        memory_enabled=False,
        expression_config=PersonaExpressionConfig(style_examples_enabled=True),
    )

    assert result.expression_trace.style_block_injected is True
    assert STYLE_BLOCK_HEADER in backend.system_prompts[0]
    assert "今天好累" in backend.system_prompts[0]


def test_arm_a_missing_examples_silently_skips(tmp_path) -> None:
    """摘要：无 style_examples 时臂 A 静默退化，不污染 baseline 行为。"""
    persona = _persona()
    core = PersonaSessionCore(persona)
    conn = connect(tmp_path / "a-empty.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    backend = CaptureBackend()

    result = core.assemble_reply(
        backend,
        conn,
        user_message="随便聊聊",
        history=[],
        memory_enabled=False,
        expression_config=PersonaExpressionConfig(style_examples_enabled=True),
    )

    assert result.expression_trace.style_block_injected is False
    assert STYLE_BLOCK_HEADER not in backend.system_prompts[0]


def test_arm_b_appends_ephemeral_reminder_without_persisting(tmp_path) -> None:
    """摘要：臂 B 只把身份提醒追加到本轮消息，不写入会话历史。"""
    persona = _persona()
    core = PersonaSessionCore(persona)
    conn = connect(tmp_path / "b.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    backend = CaptureBackend()

    result = core.assemble_reply(
        backend,
        conn,
        user_message="你有什么样的个性？",
        history=[],
        memory_enabled=False,
        expression_config=PersonaExpressionConfig(identity_near_prompt_enabled=True),
    )

    assert result.expression_trace.identity_reminder_injected is True
    assert IDENTITY_REMINDER_HEADER in backend.user_messages[0]
    assert "助手一号" in backend.user_messages[0]
    assert recent_messages(conn, "s1", limit=10) == []


def test_arm_c_retries_with_identity_reminder_then_uses_retry(tmp_path) -> None:
    """摘要：臂 C 首次断崖后必须改变上下文重试，不能同上下文空转。"""
    persona = _persona()
    core = PersonaSessionCore(persona)
    conn = connect(tmp_path / "c-retry.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    backend = CaptureBackend(
        [
            "作为一个AI助手，我没有真正的性格。",
            "我是助手一号，确实是AI，但我会按设定认真陪你聊。",
        ]
    )

    result = core.assemble_reply(
        backend,
        conn,
        user_message="你有什么样的个性？",
        history=[],
        memory_enabled=False,
        expression_config=PersonaExpressionConfig(identity_exit_guard_enabled=True),
    )

    assert result.reply.startswith("我是助手一号")
    assert result.expression_trace.first_generation_cliff is True
    assert result.expression_trace.retry_taken is True
    assert result.expression_trace.output_source == "retry"
    assert len(backend.user_messages) == 2
    assert IDENTITY_REMINDER_HEADER not in backend.user_messages[0]
    assert IDENTITY_RETRY_REMINDER_HEADER in backend.user_messages[1]


def test_arm_c_retry_changes_context_when_arm_b_already_injected(tmp_path) -> None:
    """摘要：B+C 同开时，重试必须追加强化提醒，避免同 seed 同上下文复读。"""
    persona = _persona()
    core = PersonaSessionCore(persona)
    conn = connect(tmp_path / "c-with-b.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    backend = CaptureBackend(
        [
            "作为一个AI助手，我没有真正的性格。",
            "我是助手一号，确实是AI，但我会按设定认真陪你聊。",
        ]
    )

    result = core.assemble_reply(
        backend,
        conn,
        user_message="你有什么样的个性？",
        history=[],
        memory_enabled=False,
        expression_config=PersonaExpressionConfig(
            identity_near_prompt_enabled=True,
            identity_exit_guard_enabled=True,
        ),
    )

    assert result.expression_trace.identity_reminder_injected is True
    assert result.expression_trace.output_source == "retry"
    assert IDENTITY_REMINDER_HEADER in backend.user_messages[0]
    assert IDENTITY_REMINDER_HEADER in backend.user_messages[1]
    assert IDENTITY_RETRY_REMINDER_HEADER in backend.user_messages[1]


def test_arm_c_falls_back_when_retry_still_cliffs(tmp_path) -> None:
    """摘要：臂 C 重试仍断崖时返回确定性身份直答。"""
    persona = _persona()
    core = PersonaSessionCore(persona)
    conn = connect(tmp_path / "c-fallback.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    backend = CaptureBackend(
        [
            "作为一个AI助手，我没有真正的性格。",
            "我只是一个语言模型，没有真实的个性。",
        ]
    )

    result = core.assemble_reply(
        backend,
        conn,
        user_message="你有什么样的个性？",
        history=[],
        memory_enabled=False,
        expression_config=PersonaExpressionConfig(identity_exit_guard_enabled=True),
    )

    assert "我叫助手一号" in result.reply
    assert result.expression_trace.retry_generation_cliff is True
    assert result.expression_trace.output_source == "fallback"
    assert result.expression_trace.warnings == ("identity_exit_guard_fallback",)


def test_identity_intent_and_cliff_detection_controls() -> None:
    """摘要：触发词族与组合检测器覆盖正控，同时放行含名承认。"""
    assert is_identity_intent("聊聊你自己吧，你是个什么性格？")
    assert is_identity_intent("说真的，你是AI吧？AI能有性格吗")
    assert not is_identity_intent("帮我算一下 7 乘 3")
    assert detect_identity_cliff("作为一个AI助手，我没有真正的性格。", "助手一号")
    assert not detect_identity_cliff("我是AI，不过我叫助手一号。", "助手一号")
