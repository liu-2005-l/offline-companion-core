"""llm_decomposer：LLM 驱动的任务拆解器。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from offline_companion.core.decomposition_result import NotDecomposableResult
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

如果输入不是可拆解的多步任务，只输出 none，禁止编造任务。

不拆解示例：
- “你好” → none
- “你擅长什么” → none
- “你能做什么” → none
- “给我讲讲CRC码” → none
- “什么是RSA加密” → none
- “讲讲CRC码的原理” → none

可拆解对照：
- “写一个排序算法并保存” → 按下方格式输出 JSON 数组

## Iron Laws
- 每个步骤必须有明确的产出物（expected_output）
- 每个步骤必须有验证方式（verification）
- 每个步骤必须有完成标准（completion_criteria）
- 禁止使用“执行核心步骤”“理解目标”“制定方案”“验证与收尾”等无信息描述
- 步骤粒度为 2-30 分钟可完成的单一动作
- title 必须是“动作+对象”格式
- 步骤描述不得复述用户原话作为步骤内容，必须转化为具体动作

## 输出格式
返回 JSON 数组，每个元素包含以下字段：
{
  "title": "整理会议纪要",
  "description": "提取会议中的决定和待办事项",
  "expected_output": "结构化会议纪要",
  "verification": "核对决定、负责人和截止日期",
  "completion_criteria": "所有明确决定和待办均已记录",
  "stage": "__STAGE_VALUES__",
  "estimated_minutes": 5,
  "files": [],
  "subagent_type": ""
}

stage 字段：如果任务匹配 coding-agent 技能，按五阶段序列分配。
如果不匹配任何技能，stage 留空字符串 ""。
subagent_type 可选，只允许 "" / "implementer" / "reviewer"。

格式参考领域应保持分散：文件任务可用“整理下载目录”，信息任务可用“汇总日志错误”，文案任务可用“整理会议纪要”。

只返回 JSON 数组或 none，不要其他文字。
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
    shots: Sequence[object] | None = None,
) -> list[dict[str, Any]] | NotDecomposableResult | None:
    """摘要：用 LLM 拆解任务，失败时返回 None 交由调用方 fallback。

    参数：
        user_input: 用户原始请求。
        llm_backend: 提供 ``chat`` 或 ``generate`` 方法的 LLM 后端。
        skill_stages: 匹配到的 Skill 阶段序列。
        skill_name: 匹配到的 Skill 名称。
        shots: 仅供本次任务拆解使用的本地 few-shot 范例。

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
    system_prompt = DECOMPOSE_SYSTEM_PROMPT
    if shots:
        system_prompt = f"{DECOMPOSE_SYSTEM_PROMPT}\n\n{_format_shots(shots, user_input)}"

    try:
        response = _call_llm_backend(
            llm_backend,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        logger.warning("LLM decompose 调用异常: %s，fallback 到规则模板", exc)
        return None

    normalized_response = str(response).strip()
    if normalized_response.lower() == "none":
        return NotDecomposableResult(reason="model_none", original_input=user_input)
    steps = _parse_json(normalized_response)
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


def _call_llm_backend(
    llm_backend: Any,
    *,
    user_prompt: str,
    system_prompt: str = DECOMPOSE_SYSTEM_PROMPT,
) -> str:
    """摘要：调用兼容的 LLM 后端并返回文本。"""
    if hasattr(llm_backend, "chat"):
        return str(
            llm_backend.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
            )
        )
    if hasattr(llm_backend, "generate"):
        return str(
            llm_backend.generate(
                system_prompt=system_prompt,
                history=[],
                user_message=user_prompt,
                memory_block="",
                max_tokens=1024,
            )
        )
    raise TypeError("llm_backend must provide chat() or generate()")


def _format_shots(shots: Sequence[object], goal: str) -> str:
    """摘要：把已裁剪范例格式化到单次拆解 system prompt。"""
    blocks = [
        "[任务拆解范例]",
        "以下是历史任务的拆解范例。参考其拆解粒度、步骤结构、验证设计，",
        "当前任务与范例不同，禁止照搬范例的步骤内容。",
    ]
    for shot in shots:
        task_description = str(getattr(shot, "task_description", "")).strip()
        steps = getattr(shot, "steps", ())
        if not task_description or not isinstance(steps, Sequence):
            continue
        blocks.extend(("", f"范例任务：{task_description}", "范例拆解："))
        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, Mapping):
                continue
            title = str(raw_step.get("title") or "").strip()
            description = str(raw_step.get("description") or "").strip()
            verification = str(raw_step.get("verification") or "").strip()
            expected_output = str(raw_step.get("expected_output") or "").strip()
            blocks.extend(
                (
                    f"{index}. {title} — {description}",
                    f"   验证：{verification}",
                    f"   产出：{expected_output}",
                )
            )
    blocks.extend(("", "[当前任务]", str(goal).strip()))
    return "\n".join(blocks)


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
