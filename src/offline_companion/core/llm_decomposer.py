"""llm_decomposer：LLM 驱动的任务拆解器。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from offline_companion.core.plan_enums import PlanStage

logger = logging.getLogger(__name__)

_CODING_AGENT_STAGE_VALUES = (
    PlanStage.BRAINSTORMING.value,
    PlanStage.PLANNING.value,
    PlanStage.TDD.value,
    PlanStage.REVIEW.value,
    PlanStage.FINALIZE.value,
)

DECOMPOSE_SYSTEM_PROMPT = """\
你是一个任务拆解专家。将用户请求拆解为具体的、可验证的执行步骤。

## Iron Laws
- 每个步骤必须有明确的产出物（expected_output）
- 每个步骤必须有验证方式（verification）
- 每个步骤必须有完成标准（completion_criteria）
- 禁止使用“执行核心步骤”“理解目标”“制定方案”“验证与收尾”等无信息描述
- 步骤粒度为 2-30 分钟可完成的单一动作
- title 必须是“动作+对象”格式，如“在 src/ 下创建 utils.py”

## 输出格式
返回 JSON 数组，每个元素包含以下字段：
{
  "title": "动作+对象",
  "description": "具体做什么",
  "expected_output": "产出物是什么",
  "verification": "怎么验证（命令或检查方式）",
  "completion_criteria": "什么算完成",
  "stage": "__STAGE_VALUES__",
  "estimated_minutes": 5,
  "files": ["src/utils.py"],
  "subagent_type": ""
}

stage 字段：如果任务匹配 coding-agent 技能，按五阶段序列分配。
如果不匹配任何技能，stage 留空字符串 ""。
subagent_type 可选，只允许 "" / "implementer" / "reviewer"。

只返回 JSON 数组，不要其他文字。
""".replace("__STAGE_VALUES__", "|".join(_CODING_AGENT_STAGE_VALUES))

_META_PATTERNS = (
    "执行核心步骤",
    "理解目标",
    "制定方案",
    "验证与收尾",
    "implement core",
    "understand goal",
    "make plan",
    "verify and finish",
)
_REQUIRED_FIELDS = (
    "title",
    "description",
    "expected_output",
    "verification",
    "completion_criteria",
)


def decompose_with_llm(
    user_input: str,
    llm_backend: Any,
    skill_stages: Sequence[str] | None = None,
    skill_name: str | None = None,
) -> list[dict[str, Any]] | None:
    """摘要：用 LLM 拆解任务，失败时返回 None 交由调用方 fallback。

    参数：
        user_input: 用户原始请求。
        llm_backend: 提供 ``chat`` 或 ``generate`` 方法的 LLM 后端。
        skill_stages: 匹配到的 Skill 阶段序列。
        skill_name: 匹配到的 Skill 名称。

    返回值：
        通过 schema 校验的 step 字典列表；调用失败、解析失败或校验失败时返回 None。
    """
    if llm_backend is None:
        return None

    stages = [str(stage) for stage in (skill_stages or ()) if str(stage).strip()]
    stage_hint = ""
    if stages:
        stage_hint = (
            f"\n此任务匹配技能「{skill_name or 'unknown'}」，"
            f"阶段序列为：{' -> '.join(stages)}。"
            "每个步骤必须对应其中一个阶段，按顺序排列。"
        )
    user_prompt = f"用户请求：{user_input}{stage_hint}\n\n请拆解为具体步骤，返回 JSON 数组。"

    try:
        response = _call_llm_backend(llm_backend, user_prompt=user_prompt)
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.warning("LLM decompose 调用异常: %s，fallback 到规则模板", exc)
        return None

    steps = _parse_json(str(response))
    if steps is None:
        logger.warning("LLM decompose JSON 解析失败，fallback 到规则模板")
        return None
    if not _validate_steps(steps, stages):
        logger.warning("LLM decompose schema 校验失败，fallback 到规则模板")
        return None
    aligned = _align_stages(steps, stages)
    if aligned is None:
        logger.warning("LLM decompose stage 对齐失败，fallback 到规则模板")
        return None
    return aligned


def _call_llm_backend(llm_backend: Any, *, user_prompt: str) -> str:
    """摘要：调用兼容的 LLM 后端并返回文本。"""
    if hasattr(llm_backend, "chat"):
        return str(
            llm_backend.chat(
                system_prompt=DECOMPOSE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
            )
        )
    if hasattr(llm_backend, "generate"):
        return str(
            llm_backend.generate(
                system_prompt=DECOMPOSE_SYSTEM_PROMPT,
                history=[],
                user_message=user_prompt,
                memory_block="",
                max_tokens=1024,
            )
        )
    raise TypeError("llm_backend must provide chat() or generate()")


def _parse_json(response: str) -> list[dict[str, Any]] | None:
    """摘要：从 LLM 响应中提取 JSON 数组。"""
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    parsed: Any
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    if not isinstance(parsed, list) or not parsed:
        return None
    if not all(isinstance(item, dict) for item in parsed):
        return None
    return [dict(item) for item in parsed]


def _validate_steps(steps: Sequence[Mapping[str, Any]], skill_stages: Sequence[str] | None = None) -> bool:
    """摘要：校验步骤必需字段、元模板描述和阶段白名单。"""
    del skill_stages
    for index, step in enumerate(steps):
        for field_name in _REQUIRED_FIELDS:
            value = step.get(field_name)
            if not isinstance(value, str) or not value.strip():
                logger.warning("Step %d 缺少或空字段: %s", index, field_name)
                return False
        title = str(step.get("title", ""))
        description = str(step.get("description", ""))
        haystack = f"{title}\n{description}".lower()
        for pattern in _META_PATTERNS:
            if pattern.lower() in haystack:
                logger.warning("Step %d 含元模板描述: %s", index, pattern)
                return False
        subagent_type = str(step.get("subagent_type") or "").strip()
        if subagent_type and subagent_type not in {"implementer", "reviewer"}:
            logger.warning("Step %d subagent_type 无效: %s", index, subagent_type)
            return False
    return True


def _align_stages(
    steps: list[dict[str, Any]],
    skill_stages: Sequence[str] | None,
) -> list[dict[str, Any]] | None:
    """摘要：校验 LLM 输出的 stage 是否属于 Skill 阶段序列。"""
    valid_stages = {str(stage) for stage in (skill_stages or ()) if str(stage).strip()}
    if not valid_stages:
        return steps
    for index, step in enumerate(steps):
        stage = str(step.get("stage") or "").strip()
        if not stage:
            continue
        if stage not in valid_stages:
            logger.warning("Step %d stage '%s' 不在序列 %s 中", index, stage, sorted(valid_stages))
            return None
    return steps
