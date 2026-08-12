"""skill_advance_stage：通过本地 Tool 推进受硬门禁保护的 Skill 阶段。"""

from __future__ import annotations

import sqlite3

from offline_companion.core.hard_gate import HardGate
from offline_companion.core.skill_execution_tracker import SkillExecutionTracker
from offline_companion.shared.types import ToolManifest
from offline_companion.shell.skill_router import SkillDescriptor, load_skill_descriptions
from offline_companion.shell.tool_registry.errors import ToolBlockedError
from offline_companion.shell.tool_registry.registry import ToolRegistry

TOOL_ID = "skill_advance_stage"


class SkillAdvanceStageTool:
    """摘要：校验阶段顺序，并持久化阶段开始、完成或失败状态。"""

    def __init__(self, tracker: SkillExecutionTracker, hard_gate: HardGate) -> None:
        self._tracker = tracker
        self._hard_gate = hard_gate

    def execute(
        self,
        *,
        action: str,
        skill_name: str,
        stage: str,
        session_id: str,
        evidence: str | None = None,
    ) -> dict[str, object]:
        """摘要：使用宿主注入的会话 ID 执行阶段状态变更。"""
        descriptor = self._skill_descriptor(skill_name)
        if descriptor is None:
            raise ValueError(f"unknown skill: {skill_name}")
        if action == "start":
            gate = self._hard_gate.check(session_id, skill_name, stage, descriptor.stages)
            if not bool(gate["allowed"]):
                missing = list(gate["missing"])
                raise ToolBlockedError(
                    f"阶段 '{stage}' 的前置条件未满足。",
                    data={
                        "missing_stages": missing,
                        "reason": str(gate["reason"]),
                        "message": f"请先完成以下阶段：{', '.join(missing)}" if missing else "请求的阶段不在技能序列中。",
                    },
                )
            result = self._tracker.start_stage(session_id, skill_name, stage)
        elif action == "complete":
            if not str(evidence or "").strip():
                raise ValueError("evidence is required when completing a stage")
            result = self._tracker.complete_stage(session_id, skill_name, stage, evidence)
        elif action == "fail":
            result = self._tracker.fail_stage(session_id, skill_name, stage, evidence)
        else:
            raise ValueError(f"unsupported skill stage action: {action}")
        if not bool(result.get("ok")):
            raise ValueError(str(result.get("error") or "skill stage transition failed"))
        return result

    @staticmethod
    def _skill_descriptor(skill_name: str) -> SkillDescriptor | None:
        return next((skill for skill in load_skill_descriptions() if skill.name == skill_name), None)


def register_skill_advance_stage_tool(registry: ToolRegistry, conn: sqlite3.Connection) -> SkillAdvanceStageTool:
    """摘要：注册由宿主注入 session_id 的本地阶段推进 Tool。"""
    tracker = SkillExecutionTracker(conn)
    tool = SkillAdvanceStageTool(tracker, HardGate(tracker))
    registry.register_builtin(
        ToolManifest(
            tool_id=TOOL_ID,
            display_name="Skill Stage Gate",
            description="按硬门禁开始、完成或失败一个 Skill 阶段。",
            tool_type="builtin",
            permission="allow",
            scope="local_metadata",
            params_schema={
                "type": "object",
                "required": ["action", "skill_name", "stage"],
                "properties": {
                    "action": {"type": "string", "enum": ["start", "complete", "fail"]},
                    "skill_name": {"type": "string"},
                    "stage": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
            return_schema={"type": "object"},
            handler_module="offline_companion.shell.tool_registry.skill_advance_stage",
            handler_function="execute",
            external_config=None,
            version="1.0.0",
        ),
        tool.execute,
        inject_session_id=True,
    )
    return tool
