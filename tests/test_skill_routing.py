from __future__ import annotations

from pathlib import Path

from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import Persona
from offline_companion.shell.skill_router import (
    SkillDecisionEngine,
    SkillRoutingDecision,
    load_skill_descriptions,
    match_skill,
)


def _write_skill(root: Path, name: str, description: str) -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n## Iron Laws\n\n必须验证。\n",
        encoding="utf-8",
    )
    return path


def test_coding_request_matches_coding_agent() -> None:
    decision = SkillDecisionEngine().decide("帮我写一个 Python 脚本处理 CSV 文件")

    assert decision.route == "skill"
    assert decision.skill_name == "coding-agent"
    assert decision.skill_md_path is not None


def test_chat_and_memory_request_do_not_match_skill() -> None:
    engine = SkillDecisionEngine()

    assert engine.decide("今天天气怎么样").route == "chat"
    assert engine.decide("记住我喜欢深色主题").route == "chat"


def test_memory_and_clarify_routes_have_priority(tmp_path) -> None:
    _write_skill(tmp_path, "coding-agent", "Python 脚本 写代码")
    engine = SkillDecisionEngine(tmp_path)

    assert engine.decide("Python 脚本", memory_route="memory").route == "memory"
    assert engine.decide("Python 脚本", needs_clarification=True).route == "clarify"


def test_single_keyword_does_not_trigger(tmp_path) -> None:
    _write_skill(tmp_path, "coding-agent", "Python 脚本 写代码")
    skills = load_skill_descriptions(tmp_path)

    assert match_skill("我想学 Python", skills) is None


def test_skill_path_must_remain_under_trusted_root(tmp_path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = _write_skill(tmp_path / "outside", "coding-agent", "Python 脚本")
    decision = SkillRoutingDecision(
        route="skill",
        skill_name="coding-agent",
        skill_md_path=str(outside),
    )

    assert SkillDecisionEngine(trusted).build_prompt(decision) == ""


def test_session_injects_activated_skill_after_bootstrap(tmp_path) -> None:
    skill_path = _write_skill(tmp_path / "skills", "coding-agent", "Python 脚本 写代码")
    decision = SkillRoutingDecision("skill", "coding-agent", str(skill_path))
    skill_prompt = SkillDecisionEngine(tmp_path / "skills").build_prompt(decision)
    conn = connect(tmp_path / "session.db")
    new_session(conn, "session", "persona", title=None)
    core = PersonaSessionCore(
        Persona(
            persona_id="persona",
            name="测试",
            system_prompt="基础身份",
            role_lock=True,
            memory_default_on=False,
            default_companion_display_name="助手",
            companion_display_name=None,
            raw={},
        )
    )

    _, _, system_prompt, _ = core._assemble_context(
        conn,
        user_message="写 Python 脚本",
        memory_enabled=False,
        skill_prompt=skill_prompt,
    )

    assert "## 激活技能：coding-agent" in system_prompt
    assert "必须按其 Iron Laws" in system_prompt
    assert system_prompt.index("## 技能感知") < system_prompt.index("## 激活技能")


def test_coding_skill_prompt_contains_hard_gate_sequence() -> None:
    engine = SkillDecisionEngine()
    prompt = engine.build_prompt(engine.decide("帮我写一个 Python 脚本"))

    assert "## 硬门禁：阶段序列" in prompt
    assert "brainstorming → planning → tdd → review → finalize" in prompt
    assert "skill_advance_stage" in prompt
