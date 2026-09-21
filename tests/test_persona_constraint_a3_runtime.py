"""摘要：P3-A3 逐轮接线、快照边界与审计直达信号集成测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from offline_companion.core.emotion_analyzer import EmotionContext
from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_constraint import (
    AUDIT_ARITHMETIC_RETRY_TAKEN,
    AUDIT_ARITHMETIC_WARNING_APPENDED,
    L3_INVALID_EMOTION_SIGNAL,
    L3_LOW_INTENSITY_COMFORT,
    L3_LOW_INTENSITY_CORRECTION,
    assemble_l1_prompt,
    default_frozen_l1_mapping,
    finalize_l1_prompt,
    l3_frozen_l1_mapping,
    load_persona_constraint_assets,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.errors import CloudConnectorError
from offline_companion.shared.persona_snapshot import PERSONA_SNAPSHOT_SOURCE_L1
from offline_companion.shared.types import Persona
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.session_binding import build_persona_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]


class _QueueBackend:
    """摘要：按队列返回正文并记录每次实际发送的 system prompt。"""

    label = "a3-test"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.system_prompts: list[str] = []

    def generate(self, **kwargs) -> str:
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        return self.replies.pop(0)

    def generate_stream(self, **kwargs):
        yield self.generate(**kwargs)


def _validated_runtime(tmp_path):
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    preset = next(item for item in assets.builtin_presets if item.persona_id == "builtin_wenrou")
    display_name = "测试助手"
    mapping = default_frozen_l1_mapping(preset.persona_id, assets)
    prompt = finalize_l1_prompt(assemble_l1_prompt(preset.persona_id, assets, mapping), display_name)
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
    conn = connect(tmp_path / "a3-runtime.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    proof = build_persona_snapshot(
        persona,
        source=PERSONA_SNAPSHOT_SOURCE_L1,
        effective_system_prompt=prompt,
        effective_companion_name=display_name,
    )
    conn.execute(
        """
        UPDATE sessions
        SET persona_snapshot_json = ?, persona_snapshot_schema = ?,
            persona_snapshot_sha256 = ?, persona_snapshot_source = ?
        WHERE id = ?;
        """,
        (proof.canonical_json, proof.schema, proof.sha256, proof.source, "s1"),
    )
    return assets, persona, PersonaSessionCore(persona, constraint_assets=assets), conn


def test_l3_temporary_prompt_does_not_rewrite_snapshot_or_leak_into_replay(tmp_path) -> None:
    assets, persona, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(["标准回复", "低强度回复", "再次标准回复"])
    before = conn.execute(
        "SELECT persona_snapshot_json, persona_snapshot_schema, persona_snapshot_sha256, "
        "persona_snapshot_source FROM sessions WHERE id = 's1';"
    ).fetchone()

    standard = core.assemble_reply(
        backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        emotion_context=EmotionContext(emotion="sadness", confidence=0.70),
    )
    low = core.assemble_reply(
        backend,
        conn,
        user_message="今天有点低落",
        history=[],
        memory_enabled=False,
        emotion_context=EmotionContext(emotion="sadness", confidence=0.45),
    )
    replay = core.assemble_reply(
        backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        emotion_context=EmotionContext(emotion="sadness", confidence=0.70),
    )
    after = conn.execute(
        "SELECT persona_snapshot_json, persona_snapshot_schema, persona_snapshot_sha256, "
        "persona_snapshot_source FROM sessions WHERE id = 's1';"
    ).fetchone()

    expected_low = finalize_l1_prompt(
        assemble_l1_prompt(
            persona.persona_id,
            assets,
            l3_frozen_l1_mapping(persona.persona_id, assets, L3_LOW_INTENSITY_COMFORT),
        ),
        persona.companion_display_name or "",
    )
    assert standard.l3_trace.prompt_replaced is False
    assert low.l3_trace.result == L3_LOW_INTENSITY_COMFORT
    assert low.l3_trace.prompt_replaced is True
    assert expected_low in backend.system_prompts[1]
    assert backend.system_prompts[0].encode("utf-8") == backend.system_prompts[2].encode("utf-8")
    assert replay.l3_trace.prompt_replaced is False
    assert tuple(before) == tuple(after)
    assert json.loads(after["persona_snapshot_json"])["effective_system_prompt"] == persona.system_prompt


def test_l3_standard_path_is_byte_identical_to_a2_unmanaged_path(tmp_path) -> None:
    _assets, persona, managed_core, conn = _validated_runtime(tmp_path)
    unmanaged_core = PersonaSessionCore(persona)
    managed_backend = _QueueBackend(["受管标准回复"])
    unmanaged_backend = _QueueBackend(["A2 标准回复"])

    managed_core.assemble_reply(
        managed_backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        emotion_context=EmotionContext(emotion="sadness", confidence=0.70),
        audit_arithmetic=False,
    )
    unmanaged_core.assemble_reply(
        unmanaged_backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        emotion_context=EmotionContext(emotion="sadness", confidence=0.70),
        audit_arithmetic=False,
    )

    assert managed_backend.system_prompts[0].encode("utf-8") == unmanaged_backend.system_prompts[
        0
    ].encode("utf-8")


def test_l3_standard_burned_prompt_matches_frozen_sha256_golden(tmp_path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(["标准回复"])

    core.assemble_reply(
        backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        emotion_context=EmotionContext(emotion="sadness", confidence=0.70),
        audit_arithmetic=False,
    )

    assert hashlib.sha256(backend.system_prompts[0].encode("utf-8")).hexdigest() == (
        "88befdc730346df1c2fdf30dac3e9cf2c5277d4fa194c57dea001158267ec7e8"
    )


def test_invalid_emotion_signal_disables_constraints_without_domain_event(tmp_path) -> None:
    assets, persona, core, conn = _validated_runtime(tmp_path)
    preset = next(item for item in assets.builtin_presets if item.persona_id == persona.persona_id)
    backend = _QueueBackend(["普通回复"])
    mirrored: list[tuple[str, bool]] = []

    result = core.assemble_reply(
        backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        emotion_context=EmotionContext(emotion="sadness", confidence="invalid"),  # type: ignore[arg-type]
        audit_arithmetic=False,
        audit_event_mirror=lambda event_type, consumed: mirrored.append((event_type, consumed))
        or True,
    )

    assert result.l3_trace.result == L3_INVALID_EMOTION_SIGNAL
    assert result.l3_trace.constraints_enabled is False
    assert result.l3_trace.closure_reason == L3_INVALID_EMOTION_SIGNAL
    assert result.l3_trace.prompt_replaced is True
    assert preset.base_system_prompt in backend.system_prompts[0]
    assert persona.system_prompt not in backend.system_prompts[0]
    assert result.audit_events == ()
    assert mirrored == []


def test_arithmetic_retry_reassembles_correction_prompt_even_when_event_mirror_fails(tmp_path) -> None:
    assets, persona, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(["7×3=77。", "重新核算后 7×3=21。"])
    mirrored: list[tuple[str, bool]] = []

    def fail_mirror(event_type: str, consumed: bool) -> bool:
        mirrored.append((event_type, consumed))
        return False

    result = core.assemble_reply(
        backend,
        conn,
        user_message="计算 7 乘 3",
        history=[],
        memory_enabled=False,
        audit_event_mirror=fail_mirror,
    )

    expected_correction = finalize_l1_prompt(
        assemble_l1_prompt(
            persona.persona_id,
            assets,
            l3_frozen_l1_mapping(persona.persona_id, assets, L3_LOW_INTENSITY_CORRECTION),
        ),
        persona.companion_display_name or "",
    )
    assert result.reply == "重新核算后 7×3=21。"
    assert expected_correction in backend.system_prompts[1]
    assert expected_correction not in backend.system_prompts[0]
    assert result.l3_trace.audit_event == AUDIT_ARITHMETIC_RETRY_TAKEN
    assert result.l3_trace.event_mirror_failed is True
    assert mirrored == [(AUDIT_ARITHMETIC_RETRY_TAKEN, True)]


def test_warning_meta_is_consumed_once_by_next_generation(tmp_path) -> None:
    assets, persona, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(
        ["7×3=77。", "重试仍声称 7×3=77。", "下一轮正常回复。", "第三轮正常回复。"]
    )
    orchestrator = ConversationOrchestrator(
        session_core=core,
        backend=backend,
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )

    orchestrator.run_turn("计算 7 乘 3", memory_on=False)
    warning_row = conn.execute(
        "SELECT id, meta_json FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    warning_meta = json.loads(warning_row["meta_json"])
    assert warning_meta["persona_audit_pending"] == [AUDIT_ARITHMETIC_WARNING_APPENDED]

    orchestrator.run_turn("继续", memory_on=False)
    consumed_meta = json.loads(
        conn.execute("SELECT meta_json FROM messages WHERE id = ?;", (warning_row["id"],)).fetchone()[
            "meta_json"
        ]
    )
    assert consumed_meta["persona_audit_pending"] == []
    assert consumed_meta["persona_audit_consumed_in_turn"]

    orchestrator.run_turn("再继续", memory_on=False)
    expected_correction = finalize_l1_prompt(
        assemble_l1_prompt(
            persona.persona_id,
            assets,
            l3_frozen_l1_mapping(persona.persona_id, assets, L3_LOW_INTENSITY_CORRECTION),
        ),
        persona.companion_display_name or "",
    )
    assert expected_correction in backend.system_prompts[1]
    assert expected_correction in backend.system_prompts[2]
    assert backend.system_prompts[3].encode("utf-8") == backend.system_prompts[0].encode("utf-8")


def test_stream_warning_is_mirrored_and_persisted_for_one_time_consumption(tmp_path) -> None:
    assets, persona, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(["7×3=77。", "重试仍声称 7×3=77。", "下一轮正常回复。"])
    event_stream = EventStream("a3-stream", build_default_registry())
    orchestrator = ConversationOrchestrator(
        session_core=core,
        backend=backend,
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
        event_stream=event_stream,
    )

    stream_events = list(orchestrator.run_turn_stream("计算 7 乘 3", memory_on=False))
    warning_row = conn.execute(
        "SELECT id, meta_json FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    warning_meta = json.loads(warning_row["meta_json"])
    mirrored_types = [event.event_type for event in event_stream.get_events()]

    assert stream_events[-1]["done"] is True
    assert warning_meta["persona_audit_pending"] == [AUDIT_ARITHMETIC_WARNING_APPENDED]
    assert AUDIT_ARITHMETIC_RETRY_TAKEN in mirrored_types
    assert AUDIT_ARITHMETIC_WARNING_APPENDED in mirrored_types

    orchestrator.run_turn("继续", memory_on=False)
    consumed_meta = json.loads(
        conn.execute("SELECT meta_json FROM messages WHERE id = ?;", (warning_row["id"],)).fetchone()[
            "meta_json"
        ]
    )
    expected_correction = finalize_l1_prompt(
        assemble_l1_prompt(
            persona.persona_id,
            assets,
            l3_frozen_l1_mapping(persona.persona_id, assets, L3_LOW_INTENSITY_CORRECTION),
        ),
        persona.companion_display_name or "",
    )
    assert consumed_meta["persona_audit_pending"] == []
    assert consumed_meta["persona_audit_consumed_in_turn"]
    assert expected_correction in backend.system_prompts[2]


def test_cloud_local_fallback_preserves_warning_pending_meta(tmp_path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(["7×3=77。", "重试仍声称 7×3=77。"])
    orchestrator = ConversationOrchestrator(
        session_core=core,
        backend=backend,
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )

    def fail_cloud(_request) -> None:
        raise CloudConnectorError("stub fail")

    result = orchestrator.run_cloud_turn(
        "计算 7 乘 3",
        purpose="a3-fallback",
        memory_on=False,
        cloud_post=fail_cloud,
    )
    meta = json.loads(
        conn.execute(
            "SELECT meta_json FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
        ).fetchone()["meta_json"]
    )

    assert result.cloud_degraded is True
    assert meta["persona_audit_pending"] == [AUDIT_ARITHMETIC_WARNING_APPENDED]
