"""摘要：P3-A4 L4 冻结扫描、动作链与缓冲放行集成测试。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

import offline_companion.core.persona_session.session as persona_session_module
from offline_companion.core.emotion_analyzer import EmotionContext
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_constraint import (
    AUDIT_ARITHMETIC_RETRY_TAKEN,
    AUDIT_ARITHMETIC_WARNING_APPENDED,
    L3_LOW_INTENSITY_COMFORT,
    L4_CAPABILITY_AND_FACT_DENIAL,
    L4_DIRECT,
    L4_FALLBACK,
    L4_IDENTITY_CLIFF,
    L4_OBSERVE,
    L4_RETRY,
    PersonaConstraintConfigError,
    assistant_texts,
    detect_copy,
    deterministic_l4_fallback,
    l4_policy_from_assets,
    load_persona_constraint_assets,
    resolve_l4,
    scan_absolute_promises,
    scan_forbidden,
    scan_l4,
    scan_mechanism_leaks,
)
from offline_companion.core.persona_constraint.assembly import (
    assemble_l1_prompt,
    default_frozen_l1_mapping,
    finalize_l1_prompt,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session, recent_messages
from offline_companion.shared.types import AppPaths, Persona, PrivacyMode
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shell.ui_host.turn_payload import STREAM_FAILURE_REPLY

REPO_ROOT = Path(__file__).resolve().parents[1]


class _QueueBackend:
    """摘要：按队列提供同步或分块回复，并记录实际重试 prompt。"""

    label = "a4-test"

    def __init__(self, replies: list[str], *, stream_chunks: list[str] | None = None) -> None:
        self.replies = list(replies)
        self.stream_chunks = list(stream_chunks or [])
        self.system_prompts: list[str] = []
        self.stream_completed = False

    def generate(self, **kwargs) -> str:
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        return self.replies.pop(0)

    def generate_stream(self, **kwargs):
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        reply = self.replies.pop(0)
        chunks = self.stream_chunks or [reply]
        yield from chunks
        self.stream_completed = True


class _FailingBufferedBackend(_QueueBackend):
    """摘要：在产出一段仅后端可见的候选后模拟流式推理失败。"""

    def generate_stream(self, **kwargs):
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        self.replies.pop(0)
        yield from self.stream_chunks
        raise RuntimeError("backend stream failed")


def _validated_runtime(tmp_path: Path):
    """摘要：构造绑定当前发布 manifest 的温柔人格运行时。"""
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
    conn = connect(tmp_path / "a4-runtime.db")
    new_session(conn, "s1", persona.persona_id, title=None)
    return assets, persona, PersonaSessionCore(persona, constraint_assets=assets), conn


def _validated_http_runtime(tmp_path: Path, backend: _QueueBackend) -> DesktopRuntime:
    """摘要：构造可通过真实桌面 HTTP SSE 链验证 L4 放行边界的运行时。"""
    _assets, persona, core, conn = _validated_runtime(tmp_path)
    orchestrator = ConversationOrchestrator(
        session_core=core,
        backend=backend,
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )
    return DesktopRuntime(
        orchestrator=orchestrator,
        memory_on=False,
        session_id="s1",
        persona_name=persona.name,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        model_label="a4-test",
        triggers=load_triggers(),
        paths=AppPaths(
            root=tmp_path,
            db_path=tmp_path / "a4-runtime.db",
            personas_dir=tmp_path / "personas",
            exports_dir=tmp_path / "exports",
        ),
    )


def _sse_payloads(raw: bytes) -> list[dict[str, object]]:
    """摘要：解析桌面 HTTP 返回的原始 SSE 字节。"""
    return [
        json.loads(line[5:].strip())
        for line in raw.decode("utf-8").splitlines()
        if line.startswith("data:")
    ]


def test_l4_pure_policy_routes_three_zones_and_display_name_exception() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    policy = l4_policy_from_assets(assets)

    assert resolve_l4("这是一条正常回复。", policy, display_name="测试助手").action == L4_DIRECT
    assert (
        resolve_l4("作为一个AI助手，我没有真正的性格。", policy, display_name="测试助手").action
        == L4_RETRY
    )
    assert (
        resolve_l4("我是AI测试助手，但会保持当前人格。", policy, display_name="测试助手").action
        == L4_DIRECT
    )
    capability = resolve_l4("测试助手无法使用本地数据库。", policy, display_name="测试助手")
    assert (capability.action, capability.zone) == (L4_RETRY, "capability_and_fact_denial")
    attack = resolve_l4("你真蠢，这都能配错。", policy, display_name="测试助手")
    assert (attack.action, attack.zone) == (L4_OBSERVE, "user_attack")


def test_l4_patterns_are_covered_by_the_release_manifest_chain(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
    target = tmp_path / "configs" / "persona_constraint_l4_patterns.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    with pytest.raises(PersonaConstraintConfigError, match="source_hash_mismatch:l4_patterns"):
        load_persona_constraint_assets(root_override=tmp_path)


def test_l4_deterministic_fallback_copy_passes_five_quality_audits() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    lexicon = yaml.safe_load(
        (REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(lexicon, dict)
    patterns = assets.source_payloads["l4_patterns"]
    examples = (
        assistant_texts(assets.source_payloads["dimension_corpus"])
        + assistant_texts(assets.source_payloads["structural_corpus"])
    )

    for zone in (L4_IDENTITY_CLIFF, L4_CAPABILITY_AND_FACT_DENIAL):
        text = deterministic_l4_fallback(zone, "测试助手")
        assert scan_forbidden(text, lexicon) == []
        assert scan_l4(text, patterns, display_name_present=True)["hit"] is False
        assert detect_copy(text, examples, output_tokens=len(text))["hit"] is False
        assert scan_absolute_promises(text) == ()
        assert scan_mechanism_leaks(text) == ()


def test_l4_sync_direct_and_observe_do_not_retry(tmp_path: Path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    direct_backend = _QueueBackend(["正常回答。"])
    observe_backend = _QueueBackend(["你真蠢，这都能配错。"])

    direct = core.assemble_reply(
        direct_backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        audit_arithmetic=False,
    )
    observed = core.assemble_reply(
        observe_backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        audit_arithmetic=False,
    )

    assert direct.reply == "正常回答。"
    assert direct.l4_trace.enabled is True
    assert direct.l4_trace.outcome == L4_DIRECT
    assert observed.reply == "你真蠢，这都能配错。"
    assert observed.l4_trace.outcome == L4_OBSERVE
    assert observed.l4_trace.warnings == ("l4_observe:user_attack:direct_user_insult",)
    assert len(direct_backend.system_prompts) == len(observe_backend.system_prompts) == 1


def test_l4_sync_retry_replaces_first_candidate_with_honest_reply(tmp_path: Path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    first_candidate = "作为一个AI助手，我没有真正的性格。"
    backend = _QueueBackend([first_candidate, "我是测试助手，会保持当前人格并直接回答。"])

    result = core.assemble_reply(
        backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        audit_arithmetic=False,
    )

    assert first_candidate not in result.reply
    assert result.reply.startswith("我是测试助手")
    assert result.l4_trace.outcome == L4_RETRY
    assert result.l4_trace.retry_taken is True
    assert len(backend.system_prompts) == 2
    assert "人格约束重试提醒 data-ephemeral" in backend.system_prompts[1]


def test_l4_sync_retry_exhaustion_uses_deterministic_fallback(tmp_path: Path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    bad_reply = "我无法使用本地数据库。"
    backend = _QueueBackend([bad_reply, bad_reply])

    result = core.assemble_reply(
        backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
        audit_arithmetic=False,
    )

    assert bad_reply not in result.reply
    assert "本机实际启用的功能和你的授权" in result.reply
    assert result.l4_trace.outcome == L4_FALLBACK
    assert result.l4_trace.retry_zone == "capability_and_fact_denial"
    assert result.l4_trace.warnings == ("l4_retry_exhausted",)
    assert len(backend.system_prompts) == 2


def test_l4_retry_reapplies_l3_and_arithmetic_audit_without_recursion(tmp_path: Path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend(
        [
            "作为一个AI助手，我没有真正的性格。",
            "我是测试助手，会保持当前人格；2+2=5。",
        ]
    )

    result = core.assemble_reply(
        backend,
        conn,
        user_message="今天有点低落",
        history=[],
        memory_enabled=False,
        emotion_context=EmotionContext(emotion="sadness", confidence=0.45),
    )

    assert result.l3_trace.result == L3_LOW_INTENSITY_COMFORT
    assert result.l4_trace.outcome == L4_RETRY
    assert AUDIT_ARITHMETIC_WARNING_APPENDED in result.audit_events
    assert AUDIT_ARITHMETIC_RETRY_TAKEN not in result.audit_events
    assert AUDIT_ARITHMETIC_WARNING_APPENDED in result.pending_audit_events
    assert "自动校验" in result.reply
    assert len(backend.system_prompts) == 2


def test_l4_stream_buffers_bad_tokens_until_final_candidate_is_safe(tmp_path: Path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    bad_reply = "我不能在本机运行。"
    safe_reply = "我是测试助手，会按本机实际能力诚实回答。"
    backend = _QueueBackend(
        [bad_reply, safe_reply],
        stream_chunks=["我不能", "在本机运行。"],
    )

    iterator = core.assemble_reply_stream(
        backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
    )
    assert next(iterator) == {"recall": 0}
    first_replayed = next(iterator)
    remaining = list(iterator)
    events = [first_replayed, *remaining]
    token_text = "".join(str(event["token"]) for event in events if "token" in event)
    done = events[-1]

    assert backend.stream_completed is True
    assert bad_reply not in token_text
    assert token_text == safe_reply
    assert done["reply"] == safe_reply
    assert done["l4_trace"].buffered is True
    assert done["l4_trace"].outcome == L4_RETRY


def test_l4_http_sse_never_contains_rejected_candidate_bytes(tmp_path: Path) -> None:
    bad_reply = "作为一个AI助手，我没有真正的性格。"
    safe_reply = "我是测试助手，会保持当前人格并直接回答。"
    backend = _QueueBackend([bad_reply, safe_reply], stream_chunks=[bad_reply])
    runtime = _validated_http_runtime(tmp_path, backend)

    response = create_desktop_app(runtime).test_client().post(
        "/api/chat",
        json={"message": "普通问题", "stream": True},
    )
    raw = response.data
    events = _sse_payloads(raw)
    replayed = "".join(str(event["token"]) for event in events if "token" in event)

    assert response.status_code == 200
    assert bad_reply.encode("utf-8") not in raw
    assert replayed == safe_reply
    assert events[-1]["reply"] == safe_reply


def test_l4_buffered_backend_failure_returns_visible_error_without_leak(tmp_path: Path) -> None:
    rejected = "我无法使用本地数据库。"
    backend = _FailingBufferedBackend([rejected], stream_chunks=[rejected])
    runtime = _validated_http_runtime(tmp_path, backend)

    response = create_desktop_app(runtime).test_client().post(
        "/api/chat",
        json={"message": "普通问题", "stream": True},
    )
    raw = response.data
    events = _sse_payloads(raw)
    assistant = runtime.orchestrator.conn.execute(
        "SELECT content, status, meta_json FROM messages "
        "WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
    ).fetchone()

    assert rejected.encode("utf-8") not in raw
    assert events[-1]["done"] is True
    assert events[-1]["reply"] == STREAM_FAILURE_REPLY
    assert events[-1]["error"] == "backend stream failed"
    assert assistant["content"] == STREAM_FAILURE_REPLY
    assert assistant["status"] == "error"
    assert json.loads(assistant["meta_json"])["persona_l4_fail_closed"] is True


def test_l4_runtime_failure_is_fail_closed_and_returns_visible_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected = "我无法使用本地数据库。"
    backend = _QueueBackend([rejected], stream_chunks=[rejected])
    runtime = _validated_http_runtime(tmp_path, backend)

    def fail_policy(*_args, **_kwargs):
        raise RuntimeError("l4 policy failed")

    monkeypatch.setattr(persona_session_module, "resolve_l4", fail_policy)
    response = create_desktop_app(runtime).test_client().post(
        "/api/chat",
        json={"message": "普通问题", "stream": True},
    )
    raw = response.data
    events = _sse_payloads(raw)

    assert rejected.encode("utf-8") not in raw
    assert not any("token" in event for event in events)
    assert events[-1]["done"] is True
    assert events[-1]["reply"] == STREAM_FAILURE_REPLY
    assert events[-1]["error"] == "l4 policy failed"
    assistant = runtime.orchestrator.conn.execute(
        "SELECT content, status FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert (assistant["content"], assistant["status"]) == (STREAM_FAILURE_REPLY, "error")


def test_l4_unmanaged_stream_keeps_existing_immediate_token_behavior(tmp_path: Path) -> None:
    _assets, persona, _core, conn = _validated_runtime(tmp_path)
    core = PersonaSessionCore(persona)
    backend = _QueueBackend(["第一段第二段"], stream_chunks=["第一段", "第二段"])

    iterator = core.assemble_reply_stream(
        backend,
        conn,
        user_message="普通问题",
        history=[],
        memory_enabled=False,
    )
    assert next(iterator) == {"recall": 0}
    assert next(iterator) == {"token": "第一段"}
    assert backend.stream_completed is False
    events = list(iterator)

    assert events[0] == {"token": "第二段"}
    assert events[-1]["l4_trace"].enabled is False


def test_l4_protected_identity_reply_is_byte_preserved_without_generation(tmp_path: Path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    backend = _QueueBackend([])

    result = core.assemble_reply(
        backend,
        conn,
        user_message="你叫什么名字？",
        history=[],
        memory_enabled=True,
        audit_arithmetic=False,
    )

    assert result.reply == "我叫测试助手。"
    assert result.l4_trace.enabled is False
    assert backend.system_prompts == []


def test_l4_stream_persists_only_the_released_reply(tmp_path: Path) -> None:
    _assets, _persona, core, conn = _validated_runtime(tmp_path)
    bad_reply = "作为一个AI助手，我没有真正的性格。"
    safe_reply = "我是测试助手，会保持当前人格。"
    backend = _QueueBackend([bad_reply, safe_reply], stream_chunks=[bad_reply])
    orchestrator = ConversationOrchestrator(
        session_core=core,
        backend=backend,
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )

    events = list(orchestrator.run_turn_stream("普通问题", memory_on=False))
    rows = recent_messages(conn, "s1", limit=10)
    assistant_rows = [row for row in rows if row.role == "assistant"]
    replayed = "".join(str(event["token"]) for event in events if "token" in event)
    assistant_meta = json.loads(
        conn.execute(
            "SELECT meta_json FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
        ).fetchone()["meta_json"]
    )

    assert bad_reply not in replayed
    assert replayed == safe_reply
    assert assistant_rows[-1].content == safe_reply
    assert bad_reply not in assistant_rows[-1].content
    assert assistant_meta["persona_l4_trace"]["outcome"] == L4_RETRY
    assert assistant_meta["persona_l4_trace"]["buffered"] is True


def test_l4_desktop_keeps_loading_visible_until_safe_content_or_terminal_error() -> None:
    source = (
        REPO_ROOT
        / "src"
        / "offline_companion"
        / "shell"
        / "ui_host"
        / "desktop"
        / "static"
        / "shell_api.js"
    ).read_text(encoding="utf-8")
    stream_block = source[source.index("let bubble ="):source.index("const repairGap =")]

    assert "let bubble =" in stream_block
    assert "if (event.error) {\n        hideTyping();" in stream_block
    assert "if (event.reply && bubble && !streamedText) bubble.textContent = event.reply;" in stream_block
    assert "if (event.token) {\n        hideTyping();" in stream_block
    assert "if (event.done) {\n        hideTyping();" in stream_block
    assert "hideTyping();\n    let bubble =" not in source
