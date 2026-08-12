from __future__ import annotations

import sqlite3

from offline_companion.core.hard_gate import HardGate
from offline_companion.core.skill_execution_tracker import SkillExecutionTracker
from offline_companion.shared.types import PrivacyMode
from offline_companion.shell.tool_registry import (
    ToolInvoker,
    ToolRegistry,
    register_skill_advance_stage_tool,
)

STAGES = ("brainstorming", "planning", "tdd", "review", "finalize")


def _tracker(tmp_path) -> SkillExecutionTracker:
    return SkillExecutionTracker(sqlite3.connect(tmp_path / "skill.db"))


def test_tracker_creates_table_and_persists_evidence(tmp_path) -> None:
    db_path = tmp_path / "skill.db"
    conn = sqlite3.connect(db_path)
    tracker = SkillExecutionTracker(conn)
    started = tracker.start_stage("s1", "coding-agent", "brainstorming")
    completed = tracker.complete_stage("s1", "coding-agent", "brainstorming", "需求已明确")

    assert started["status"] == "executing"
    assert completed["status"] == "completed"
    assert tracker.get_progress("s1", "coding-agent")[0]["evidence"] == "需求已明确"
    conn.close()

    restarted = SkillExecutionTracker(sqlite3.connect(db_path))
    assert restarted.check_prerequisite("s1", "coding-agent", "brainstorming") is True


def test_tracker_prevents_invalid_terminal_transitions(tmp_path) -> None:
    tracker = _tracker(tmp_path)

    assert tracker.complete_stage("s1", "coding-agent", "planning", "证据")["ok"] is False
    tracker.start_stage("s1", "coding-agent", "brainstorming")
    tracker.complete_stage("s1", "coding-agent", "brainstorming", "证据")
    restarted = tracker.start_stage("s1", "coding-agent", "brainstorming")
    assert restarted == {
        "ok": False,
        "error": "stage_already_completed",
        "execution_id": restarted["execution_id"],
    }


def test_hard_gate_enforces_all_prerequisites(tmp_path) -> None:
    tracker = _tracker(tmp_path)
    gate = HardGate(tracker)

    assert gate.check("s1", "coding-agent", "brainstorming", STAGES)["allowed"] is True
    planning = gate.check("s1", "coding-agent", "planning", STAGES)
    assert planning["allowed"] is False
    assert planning["missing"] == ["brainstorming"]

    tracker.start_stage("s1", "coding-agent", "brainstorming")
    tracker.complete_stage("s1", "coding-agent", "brainstorming", "需求")
    assert gate.check("s1", "coding-agent", "planning", STAGES)["allowed"] is True
    assert gate.check("s1", "coding-agent", "tdd", STAGES)["missing"] == ["planning"]


def test_hard_gate_rejects_unknown_stage_but_skips_unstaged_skill(tmp_path) -> None:
    gate = HardGate(_tracker(tmp_path))

    assert gate.check("s1", "coding-agent", "unknown", STAGES)["reason"] == "unknown_stage"
    assert gate.check("s1", "writing-plans", "anything", ())["allowed"] is True


def test_skill_advance_tool_blocks_skip_and_allows_next_stage(tmp_path) -> None:
    registry = ToolRegistry()
    register_skill_advance_stage_tool(registry, sqlite3.connect(tmp_path / "tool.db"))
    invoker = ToolInvoker(registry)

    blocked = invoker.execute(
        "skill_advance_stage",
        {"action": "start", "skill_name": "coding-agent", "stage": "planning"},
        session_id="trusted-session",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )
    assert blocked.status == "blocked"
    assert blocked.result["missing_stages"] == ["brainstorming"]

    started = invoker.execute(
        "skill_advance_stage",
        {
            "action": "start",
            "skill_name": "coding-agent",
            "stage": "brainstorming",
            "session_id": "spoofed-session",
        },
        session_id="trusted-session",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )
    completed = invoker.execute(
        "skill_advance_stage",
        {
            "action": "complete",
            "skill_name": "coding-agent",
            "stage": "brainstorming",
            "evidence": "需求边界已确认",
        },
        session_id="trusted-session",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )
    next_stage = invoker.execute(
        "skill_advance_stage",
        {"action": "start", "skill_name": "coding-agent", "stage": "planning"},
        session_id="trusted-session",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )

    assert started.status == "completed"
    assert completed.status == "completed"
    assert next_stage.status == "completed"


def test_complete_requires_evidence(tmp_path) -> None:
    registry = ToolRegistry()
    register_skill_advance_stage_tool(registry, sqlite3.connect(tmp_path / "evidence.db"))
    invoker = ToolInvoker(registry)
    invoker.execute(
        "skill_advance_stage",
        {"action": "start", "skill_name": "coding-agent", "stage": "brainstorming"},
        session_id="s1",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )

    result = invoker.execute(
        "skill_advance_stage",
        {"action": "complete", "skill_name": "coding-agent", "stage": "brainstorming"},
        session_id="s1",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )

    assert result.status == "error"
    assert result.error["code"] == "tool_execution_failed"
