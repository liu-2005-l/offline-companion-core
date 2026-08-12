"""hard_gate：检查 Skill 阶段顺序的本地流程门禁。"""

from __future__ import annotations

from offline_companion.core.skill_execution_tracker import SkillExecutionTracker


class HardGate:
    """摘要：在阶段开始前验证所有前置阶段均已完成。"""

    def __init__(self, tracker: SkillExecutionTracker) -> None:
        self._tracker = tracker

    def check(
        self,
        session_id: str,
        skill_name: str,
        requested_stage: str,
        stages: tuple[str, ...] | list[str],
    ) -> dict[str, object]:
        """摘要：返回阶段是否允许开始及缺失前置阶段。"""
        sequence = tuple(stages)
        if not sequence:
            return {"allowed": True, "missing": [], "reason": "no_stage_sequence"}
        if requested_stage not in sequence:
            return {"allowed": False, "missing": [], "reason": "unknown_stage"}
        index = sequence.index(requested_stage)
        if index == 0:
            return {"allowed": True, "missing": [], "reason": "first_stage"}
        missing = [
            prerequisite
            for prerequisite in sequence[:index]
            if not self._tracker.check_prerequisite(session_id, skill_name, prerequisite)
        ]
        if missing:
            return {"allowed": False, "missing": missing, "reason": "prerequisite_not_completed"}
        return {"allowed": True, "missing": [], "reason": "all_prerequisites_met"}
