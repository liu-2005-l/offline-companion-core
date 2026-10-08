"""摘要：W3-P2-1b 跨轮复读门接线、共享重试槽位与 trace 验收。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from scripts.persona_runner_audit import CaptureSink

import offline_companion.core.persona_session.session as persona_session_module
from offline_companion.core.persona_constraint import (
    L4_CAPABILITY_AND_FACT_DENIAL,
    L4_DIRECT,
    L4_FALLBACK,
    L4_RETRY,
    PersonaL4Decision,
    assemble_l1_prompt,
    default_frozen_l1_mapping,
    deterministic_l4_fallback,
    finalize_l1_prompt,
    load_persona_constraint_assets,
)
from offline_companion.core.persona_session.expression import PersonaExpressionConfig
from offline_companion.core.persona_session.repetition_guard import (
    CrossTurnRepetitionDecision,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import MessageRow, Persona
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator

REPO_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REPLY = "review package documentation tests release checklist before proceeding"
SAFE_REPLY = "the next response uses unrelated wording and advances the task"
SAFE_RETRY_REPLY = "a fresh answer now moves directly to the requested implementation"


class _QueueBackend:
    """摘要：按队列生成同步或流式候选，并记录模型实际收到的输入。"""

    label = "w3-p2-1b-test"

    def __init__(self, replies: list[str], *, stream_chunks: list[str] | None = None) -> None:
        self.replies = list(replies)
        self.stream_chunks = list(stream_chunks or [])
        self.system_prompts: list[str] = []
        self.user_messages: list[str] = []

    def generate(self, **kwargs: Any) -> str:
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        self.user_messages.append(str(kwargs.get("user_message") or ""))
        return self.replies.pop(0)

    def generate_stream(self, **kwargs: Any) -> Iterator[str]:
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        self.user_messages.append(str(kwargs.get("user_message") or ""))
        reply = self.replies.pop(0)
        yield from self.stream_chunks or [reply]


def _validated_runtime(tmp_path: Path) -> tuple[Any, PersonaSessionCore, Any]:
    """摘要：构造绑定当前发布 manifest 的内置人格运行时。"""

    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    preset = next(item for item in assets.builtin_presets if item.persona_id == "builtin_wenrou")
    display_name = "测试助手"
    mapping = default_frozen_l1_mapping(preset.persona_id, assets)
    prompt = finalize_l1_prompt(
        assemble_l1_prompt(preset.persona_id, assets, mapping),
        display_name,
    )
    persona = Persona(
        persona_id=preset.persona_id,
        name=preset.name,
        system_prompt=prompt,
        role_lock=True,
        memory_default_on=False,
        default_companion_display_name=display_name,
        companion_display_name=display_name,
        raw={
            "validation_status": "validated_anchor",
            "validated_anchor_id": preset.persona_id,
            "constraint_manifest_sha256": assets.manifest_sha256,
            "constraint_manifest_version": str(assets.manifest["version"]),
        },
    )
    conn = connect(tmp_path / "w3-p2-1b.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    return assets, PersonaSessionCore(persona, constraint_assets=assets), conn


def _assistant_history(content: str = PREVIOUS_REPLY) -> list[MessageRow]:
    return [MessageRow(role="assistant", content=content, created_at=1.0, meta={})]


def _enabled_config(*, identity: bool = False) -> PersonaExpressionConfig:
    return PersonaExpressionConfig(
        identity_near_prompt_enabled=identity,
        cross_turn_repetition_guard_enabled=True,
    )


def test_disabled_guard_still_emits_aggregateable_bypass_trace(tmp_path: Path) -> None:
    """摘要：默认关闭时仍产出带首判定的 guard_disabled 轨迹。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend([PREVIOUS_REPLY])

    result = core.assemble_reply(
        backend,
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
    )

    assert result.reply == PREVIOUS_REPLY
    assert result.repetition_trace.enabled is False
    assert result.repetition_trace.outcome == "bypass"
    assert result.repetition_trace.first == CrossTurnRepetitionDecision(
        action="bypass",
        reason="guard_disabled",
    )
    assert len(backend.system_prompts) == 1


def test_capture_sink_is_read_only_and_none_path_never_pushes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要：有无 sink 的装配结果逐字段一致，空旁路不得触发 push。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    push_calls = 0
    original_push = CaptureSink.push

    def counted_push(self: CaptureSink, *args: Any, **kwargs: Any) -> None:
        nonlocal push_calls
        push_calls += 1
        original_push(self, *args, **kwargs)

    monkeypatch.setattr(CaptureSink, "push", counted_push)
    without_sink = core.assemble_reply(
        _QueueBackend([SAFE_REPLY]),
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
        capture_sink=None,
    )

    assert push_calls == 0

    sink = CaptureSink()
    with_sink = core.assemble_reply(
        _QueueBackend([SAFE_REPLY]),
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
        capture_sink=sink,
    )
    captures = sink.drain()

    assert with_sink == without_sink
    assert push_calls == 1
    assert len(captures) == 1
    assert captures[0]["phase"] == "first"
    assert captures[0]["text"] == SAFE_REPLY
    assert captures[0]["l4_decision"] is not None
    assert captures[0]["repetition_decision"] == with_sink.repetition_trace.first


def test_capture_sink_records_first_and_retry_with_original_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要：共享 retry 的两次候选均保存双门 DTO 与判定原始分数。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    first_decision = CrossTurnRepetitionDecision(
        action="retry",
        score=0.123456789,
        threshold=0.09,
        reason="threshold_exceeded",
    )
    retry_decision = CrossTurnRepetitionDecision(
        action="direct",
        score=0.012345678,
        threshold=0.09,
        reason="below_threshold",
    )
    decisions = iter((first_decision, retry_decision))
    monkeypatch.setattr(
        persona_session_module,
        "decide_cross_turn_repetition",
        lambda *args, **kwargs: next(decisions),
    )
    sink = CaptureSink()

    result = core.assemble_reply(
        _QueueBackend([PREVIOUS_REPLY, SAFE_RETRY_REPLY]),
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
        capture_sink=sink,
    )
    captures = sink.drain()

    assert result.reply == SAFE_RETRY_REPLY
    assert [item["phase"] for item in captures] == ["first", "retry"]
    assert all(item["l4_decision"] is not None for item in captures)
    assert captures[0]["repetition_decision"] == first_decision
    assert captures[1]["repetition_decision"] == retry_decision
    assert captures[0]["repetition_decision"].score == 0.123456789
    assert captures[1]["repetition_decision"].score == 0.012345678


def test_capture_sink_direct_path_contains_only_first_candidate(
    tmp_path: Path,
) -> None:
    """摘要：未消费重试槽位时 uniform capture 仍只记录 first。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    sink = CaptureSink()

    result = core.assemble_reply(
        _QueueBackend([SAFE_REPLY]),
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
        capture_sink=sink,
    )
    captures = sink.drain()

    assert result.repetition_trace.retry_taken is False
    assert len(captures) == 1
    assert captures[0]["phase"] == "first"
    assert captures[0]["text"] == SAFE_REPLY


@pytest.mark.parametrize(
    ("replies", "expected_reply", "expected_outcome", "expected_calls"),
    [
        ([SAFE_REPLY], SAFE_REPLY, "direct", 1),
        ([PREVIOUS_REPLY, SAFE_RETRY_REPLY], SAFE_RETRY_REPLY, "retry", 2),
        ([PREVIOUS_REPLY, PREVIOUS_REPLY], "fallback", "fallback", 2),
    ],
)
def test_guard_sync_direct_retry_and_fallback_states(
    tmp_path: Path,
    replies: list[str],
    expected_reply: str,
    expected_outcome: str,
    expected_calls: int,
) -> None:
    """摘要：同步出口覆盖 direct、一次 retry 后 direct 与 retry 耗尽 fallback。"""

    assets, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(replies)

    result = core.assemble_reply(
        backend,
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
    )

    resolved_expected = (
        assets.cross_turn_repetition_fallback
        if expected_reply == "fallback"
        else expected_reply
    )
    assert result.reply == resolved_expected
    assert result.repetition_trace.enabled is True
    assert result.repetition_trace.outcome == expected_outcome
    assert len(backend.system_prompts) == expected_calls <= 2
    if expected_calls == 2:
        assert result.repetition_trace.retry_taken is True
        assert "data-ephemeral" in backend.system_prompts[1]


@pytest.mark.parametrize(
    ("history", "reason"),
    [
        ([], "missing_previous_or_current_reply"),
        ([MessageRow(role="user", content="earlier", created_at=1.0, meta={})], "not_adjacent_pair"),
    ],
)
def test_guard_only_uses_adjacent_assistant_history(
    tmp_path: Path,
    history: list[MessageRow],
    reason: str,
) -> None:
    """摘要：空历史或末条非 assistant 时必须旁路，不向前搜索旧回复。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend([PREVIOUS_REPLY])

    result = core.assemble_reply(
        backend,
        conn,
        user_message="ordinary request",
        history=history,
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
    )

    assert result.repetition_trace.first is not None
    assert result.repetition_trace.first.reason == reason
    assert result.repetition_trace.outcome == "bypass"
    assert len(backend.system_prompts) == 1


def test_raw_user_message_controls_exemption_before_identity_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要：身份近端提醒改写不得污染确认意图豁免使用的原始用户输入。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend([PREVIOUS_REPLY])
    monkeypatch.setattr(persona_session_module, "is_identity_intent", lambda _text: True)

    result = core.assemble_reply(
        backend,
        conn,
        user_message="好的",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(identity=True),
    )

    assert backend.user_messages[0] != "好的"
    assert len(backend.user_messages[0]) > 32
    assert result.repetition_trace.first is not None
    assert result.repetition_trace.first.reason == "user_confirmation_exempt"
    assert result.repetition_trace.first.confirmation_intent is True
    assert len(backend.system_prompts) == 1


def test_raw_user_message_none_does_not_open_exemption(tmp_path: Path) -> None:
    """摘要：raw 缺失时确认豁免关闭，重复候选仍进入一次共享 retry。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend([SAFE_RETRY_REPLY])

    finalized = core._finalize_generated_reply(
        backend,
        conn,
        reply=PREVIOUS_REPLY,
        history=_assistant_history(),
        user_message="好的",
        raw_user_message=None,
        memory_block="",
        max_tokens=128,
        emotion_context=None,
        capability_profile=None,
        skill_prompt="",
        expression_config=_enabled_config(),
        active_signals=persona_session_module.PersonaTurnSignals(),
        initial_l3_trace=persona_session_module.PersonaL3Trace(),
        audit_arithmetic=False,
        audit_event_mirror=None,
    )

    assert finalized.reply == SAFE_RETRY_REPLY
    assert finalized.repetition_trace.first.action == "retry"
    assert finalized.repetition_trace.retry_taken is True


@pytest.mark.parametrize(
    (
        "first_reply",
        "retry_reply",
        "l4_actions",
        "expected_kind",
        "expected_l4_outcome",
        "expected_guard_outcome",
        "expected_guard_retry_taken",
    ),
    [
        (SAFE_REPLY, None, (L4_DIRECT,), "first", L4_DIRECT, "direct", False),
        (
            PREVIOUS_REPLY,
            SAFE_RETRY_REPLY,
            (L4_DIRECT, L4_DIRECT),
            "retry",
            L4_DIRECT,
            "retry",
            True,
        ),
        (
            PREVIOUS_REPLY,
            PREVIOUS_REPLY,
            (L4_DIRECT, L4_DIRECT),
            "guard",
            L4_DIRECT,
            "fallback",
            True,
        ),
        (
            PREVIOUS_REPLY,
            PREVIOUS_REPLY,
            (L4_RETRY, L4_RETRY),
            "l4",
            L4_FALLBACK,
            "retry",
            True,
        ),
        (
            SAFE_REPLY,
            PREVIOUS_REPLY,
            (L4_RETRY, L4_DIRECT),
            "guard",
            L4_RETRY,
            "fallback",
            False,
        ),
        (
            SAFE_REPLY,
            SAFE_RETRY_REPLY,
            (L4_RETRY, L4_DIRECT),
            "retry",
            L4_RETRY,
            "retry",
            False,
        ),
        (
            PREVIOUS_REPLY,
            SAFE_RETRY_REPLY,
            (L4_DIRECT, L4_RETRY),
            "l4",
            L4_FALLBACK,
            "retry",
            True,
        ),
    ],
)
def test_l4_and_guard_share_one_retry_slot_with_l4_fallback_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_reply: str,
    retry_reply: str | None,
    l4_actions: tuple[str, ...],
    expected_kind: str,
    expected_l4_outcome: str,
    expected_guard_outcome: str,
    expected_guard_retry_taken: bool,
) -> None:
    """摘要：六格交互及复检新红点均共用单槽，且 L4 fallback 优先。"""

    assets, core, conn = _validated_runtime(tmp_path)
    replies = [first_reply] + ([retry_reply] if retry_reply is not None else [])
    backend = _QueueBackend(replies)
    decisions = iter(l4_actions)

    def resolve_l4(_text: str, _policy: Any, *, display_name: str) -> PersonaL4Decision:
        del display_name
        action = next(decisions)
        if action == L4_RETRY:
            return PersonaL4Decision(
                action=L4_RETRY,
                zone=L4_CAPABILITY_AND_FACT_DENIAL,
                family="test_family",
            )
        return PersonaL4Decision(action=L4_DIRECT)

    monkeypatch.setattr(core, "_resolve_l4_or_raise", resolve_l4)

    result = core.assemble_reply(
        backend,
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
    )

    expected = {
        "first": first_reply,
        "retry": retry_reply,
        "guard": assets.cross_turn_repetition_fallback,
        "l4": deterministic_l4_fallback(
            core._l4_policy,
            L4_CAPABILITY_AND_FACT_DENIAL,
            "测试助手",
        ),
    }[expected_kind]
    assert result.reply == expected
    assert result.l4_trace.outcome == expected_l4_outcome
    assert result.repetition_trace.outcome == expected_guard_outcome
    assert result.repetition_trace.retry_taken is expected_guard_retry_taken
    assert len(backend.system_prompts) <= 2


def test_guard_failure_is_visible_and_fails_open_without_cross_turn_fuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要：guard 异常仅让本轮直通并留痕，下一轮继续正常判定。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    original = persona_session_module.decide_cross_turn_repetition
    calls = 0

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("guard failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(persona_session_module, "decide_cross_turn_repetition", fail_once)
    first_backend = _QueueBackend([PREVIOUS_REPLY])
    first = core.assemble_reply(
        first_backend,
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
    )
    second_backend = _QueueBackend([PREVIOUS_REPLY, SAFE_RETRY_REPLY])
    second = core.assemble_reply(
        second_backend,
        conn,
        user_message="ordinary request",
        history=_assistant_history(),
        memory_enabled=False,
        audit_arithmetic=False,
        expression_config=_enabled_config(),
    )

    assert first.reply == PREVIOUS_REPLY
    assert first.repetition_trace.first.reason == "guard_error"
    assert first.repetition_trace.outcome == "bypass"
    assert second.reply == SAFE_RETRY_REPLY
    assert second.repetition_trace.first.action == "retry"
    assert len(second_backend.system_prompts) == 2


def test_guard_stream_buffers_rejected_candidate_and_reports_trace(tmp_path: Path) -> None:
    """摘要：流式路径在复读门启用时不得先泄露被拒候选字节。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(
        [PREVIOUS_REPLY, SAFE_RETRY_REPLY],
        stream_chunks=[PREVIOUS_REPLY[:20], PREVIOUS_REPLY[20:]],
    )

    events = list(
        core.assemble_reply_stream(
            backend,
            conn,
            user_message="ordinary request",
            history=_assistant_history(),
            memory_enabled=False,
            expression_config=_enabled_config(),
        )
    )
    token_text = "".join(str(event["token"]) for event in events if "token" in event)
    done = events[-1]

    assert PREVIOUS_REPLY not in token_text
    assert token_text == SAFE_RETRY_REPLY
    assert done["reply"] == SAFE_RETRY_REPLY
    assert done["repetition_trace"].outcome == "retry"
    assert len(backend.system_prompts) == 2


def test_stream_raw_split_and_meta_serialization_keep_independent_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要：流式 raw 分线与 assistant meta 均保留独立复读轨迹。"""

    _assets, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend([PREVIOUS_REPLY], stream_chunks=[PREVIOUS_REPLY])
    monkeypatch.setattr(persona_session_module, "is_identity_intent", lambda _text: True)

    events = list(
        core.assemble_reply_stream(
            backend,
            conn,
            user_message="好的",
            history=_assistant_history(),
            memory_enabled=False,
            expression_config=_enabled_config(identity=True),
        )
    )
    trace = events[-1]["repetition_trace"]
    meta = ConversationOrchestrator._persona_meta(None, None, (), trace)

    assert len(backend.user_messages[0]) > 32
    assert trace.first.reason == "user_confirmation_exempt"
    assert meta["cross_turn_repetition_trace"] == asdict(trace)
