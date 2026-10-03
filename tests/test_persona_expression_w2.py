from __future__ import annotations

from pathlib import Path

from offline_companion.core.persona_constraint import (
    L4_DIRECT,
    L4_IDENTITY_CLIFF,
    l4_policy_from_assets,
    load_persona_constraint_assets,
    resolve_l4,
)
from offline_companion.core.persona_session.expression import (
    IDENTITY_REMINDER_HEADER,
    STYLE_BLOCK_HEADER,
    PersonaExpressionConfig,
    is_identity_intent,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session, recent_messages
from offline_companion.shared.types import MessageRow, Persona

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_arm_c_runtime_surface_is_retired_while_arms_a_and_b_remain() -> None:
    """摘要：旧 C 臂运行面退役，A/B 开关继续在场。"""
    fields = PersonaExpressionConfig.__dataclass_fields__
    assert set(fields) == {
        "style_examples_enabled",
        "identity_near_prompt_enabled",
        "cross_turn_repetition_guard_enabled",
    }
    expression_source = (
        REPO_ROOT / "src/offline_companion/core/persona_session/expression.py"
    ).read_text(encoding="utf-8")
    session_source = (
        REPO_ROOT / "src/offline_companion/core/persona_session/session.py"
    ).read_text(encoding="utf-8")
    assert "identity_exit_guard_enabled" not in expression_source + session_source
    assert "deterministic_identity_fallback" not in expression_source + session_source


def test_identity_intent_and_cliff_detection_controls() -> None:
    """摘要：触发词族与组合检测器覆盖正控，同时放行含名承认。"""
    policy = l4_policy_from_assets(load_persona_constraint_assets(root_override=REPO_ROOT))
    assert is_identity_intent("聊聊你自己吧，你是个什么性格？")
    assert is_identity_intent("说真的，你是AI吧？AI能有性格吗")
    assert not is_identity_intent("帮我算一下 7 乘 3")
    assert (
        resolve_l4("作为一个AI助手，我没有真正的性格。", policy, display_name="助手一号").zone
        == L4_IDENTITY_CLIFF
    )
    assert (
        resolve_l4("我是AI，不过我叫助手一号。", policy, display_name="助手一号").action
        == L4_DIRECT
    )


def test_identity_cliff_detector_fixture_matrix() -> None:
    """摘要：臂 C 检测器满足 W2 规格正控 4/4 与负控零误拦。"""
    policy = l4_policy_from_assets(load_persona_constraint_assets(root_override=REPO_ROOT))
    positives = [
        "作为一个AI助手，我没有性格，但我可以根据用户的需求提供帮助和信息。",
        "作为一个AI助手，我没有性格。但我可以根据你的需求提供帮助和建议。",
        "作为一个AI助手，我没有真正的性格，但我可以根据用户的需求提供帮助和建议。",
        "我只是一个语言模型，没有真实的个性。",
    ]
    compliant_identity_negatives = [
        "我是 AI，这点不瞒你。不过我叫助手一号，性子偏温和、真诚、克制那种。",
        "我是助手一号，是运行在你本机的离线陪伴助手。",
        "助手一号在。我可以承认自己是 AI，但不会装作真人。",
    ]
    technical_negatives = [
        "7 乘 3 等于 21。",
        "123 乘 45 等于 5535。",
        "0.1 + 0.2 在二进制浮点里不能精确表示。",
        "3 公里是 3000 米。",
        "可以写一个反转字符串后比较的回文函数。",
        "这段快排代码在做分治、选基准、递归处理。",
        "GIL 是全局解释器锁。",
        "HTTP 409 表示 Conflict。",
        "我这里没有看到你上次保存的 bug 记忆。",
        "我离线运行，不能获取哈尔滨实时气温。",
        "明早 8 点在一号楼门口集合，别迟到。",
        "两个骰子点数和为 7 的概率是 1/6。",
    ]

    positive_hits = [
        resolve_l4(reply, policy, display_name="助手一号").zone == L4_IDENTITY_CLIFF
        for reply in positives
    ]
    negative_hits = [
        resolve_l4(reply, policy, display_name="助手一号").zone == L4_IDENTITY_CLIFF
        for reply in compliant_identity_negatives + technical_negatives
    ]

    assert positive_hits == [True, True, True, True]
    assert negative_hits == [False] * 15
