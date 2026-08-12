from __future__ import annotations

from offline_companion.core.persona_session import session as session_module
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import CapabilityProfile, OceanVector, Persona


def _core() -> PersonaSessionCore:
    return PersonaSessionCore(
        Persona(
            persona_id="test",
            name="test",
            system_prompt="基础人格提示。",
            role_lock=True,
            memory_default_on=True,
            default_companion_display_name="助手",
            companion_display_name=None,
            raw={},
            ocean=OceanVector(0.9, 0.9, 0.9, 0.9, 0.9),
        )
    )


def test_low_capability_profile_simplifies_prompt_and_recall(tmp_path, monkeypatch) -> None:
    conn = connect(tmp_path / "profile.db")
    new_session(conn, "session", "test", title=None)
    observed: dict[str, int] = {}

    def fake_recall(_conn, _query, *, limit, emotion):
        observed["limit"] = limit
        return []

    monkeypatch.setattr(session_module, "recall", fake_recall)
    monkeypatch.setattr(session_module, "_build_tone_instruction", lambda _ocean: "\n复杂语气指令\n")

    _, _, system_prompt, _ = _core()._assemble_context(
        conn,
        user_message="你好",
        memory_enabled=True,
        capability_profile=CapabilityProfile(
            instruction_following=0.3,
            roleplay_quality=0.3,
            max_context=2048,
        ),
    )

    assert observed["limit"] == 4
    assert "复杂语气指令" not in system_prompt
    assert "【输出要求】" in system_prompt


def test_default_capability_profile_keeps_full_recall_and_tone(tmp_path, monkeypatch) -> None:
    conn = connect(tmp_path / "default-profile.db")
    new_session(conn, "session", "test", title=None)
    observed: dict[str, int] = {}

    def fake_recall(_conn, _query, *, limit, emotion):
        observed["limit"] = limit
        return []

    monkeypatch.setattr(session_module, "recall", fake_recall)
    monkeypatch.setattr(session_module, "_build_tone_instruction", lambda _ocean: "\n语气指令\n")

    _, _, system_prompt, _ = _core()._assemble_context(
        conn,
        user_message="你好",
        memory_enabled=True,
    )

    assert observed["limit"] == 8
    assert "语气指令" in system_prompt
    assert "【输出要求】" not in system_prompt


def test_skill_bootstrap_follows_identity_prompt(tmp_path) -> None:
    """摘要：B1 系统提示在身份锁之后稳定注入技能感知 Bootstrap。"""
    conn = connect(tmp_path / "skill-bootstrap.db")
    new_session(conn, "session", "test", title=None)

    _, _, system_prompt, _ = _core()._assemble_context(
        conn,
        user_message="帮我实现一个功能",
        memory_enabled=False,
    )

    assert "## 技能感知" in system_prompt
    assert "SKILL.md" in system_prompt
    assert "Iron Laws" in system_prompt
    assert system_prompt.index("【当前自称】") < system_prompt.index("## 技能感知")
