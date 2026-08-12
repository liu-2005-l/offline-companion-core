from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from offline_companion.core.plan_decomposer import (
    PlanDecomposer,
    _rule_step,
    raw_to_plan_step,
    rule_decompose,
)
from offline_companion.core.plan_orchestrator import PlanStep
from offline_companion.shared.errors import A2PlanValidationError


def _valid_raw_step() -> dict[str, object]:
    """摘要：构造通过 schema 校验的原始步骤。"""
    return {
        "title": "创建 sort.py",
        "description": "在 src 下创建排序模块。",
        "expected_output": "src/sort.py 文件存在。",
        "verification": "运行 python -m pytest tests/test_sort.py。",
        "completion_criteria": "排序测试全绿。",
        "stage": "tdd",
        "estimated_minutes": 5,
        "files": ["src/sort.py"],
        "subagent_type": "implementer",
    }


def test_decide_returns_plan_steps() -> None:
    """摘要：decide() 返回强类型 PlanStep 列表。"""
    decomposer = PlanDecomposer()

    steps = decomposer.decide("实现一个本地验证脚本")

    assert steps
    assert all(isinstance(step, PlanStep) for step in steps)
    assert steps[0].title
    assert steps[0].expected_output
    assert steps[0].verification


def test_rule_decompose_fallback() -> None:
    """摘要：LLM 不可用时规则 fallback 生成可用步骤。"""
    backend = MagicMock()
    backend.chat.side_effect = RuntimeError("no model")
    decomposer = PlanDecomposer(llm_router=backend)

    steps = decomposer.decide("写一个 CSV 处理脚本")

    assert len(steps) == 5
    assert all(step.title and step.completion_criteria for step in steps)
    assert all("执行核心步骤" not in step.title for step in steps)


def test_raw_to_plan_step_rejects_meta_template() -> None:
    """摘要：元模板步骤被强类型转换前的 schema 校验拦截。"""
    raw = _valid_raw_step()
    raw["title"] = "执行核心步骤"

    with pytest.raises(A2PlanValidationError, match="meta template"):
        raw_to_plan_step(raw, "写一个排序算法", 0)


def test_raw_to_plan_step_parses_valid_step() -> None:
    """摘要：合法 LLM 输出正确解析为 PlanStep。"""
    step = raw_to_plan_step(_valid_raw_step(), "写一个排序算法", 0)

    assert step.step_id == "step_0"
    assert step.skill_id == "chat"
    assert step.result_key == "step_0_result"
    assert step.title == "创建 sort.py"
    assert step.stage == "tdd"
    assert step.files == ("src/sort.py",)
    assert step.subagent_type == "implementer"
    assert step.payload["query"] == "写一个排序算法"


def test_rule_step_has_all_required_fields() -> None:
    """摘要：规则步骤含展示、产出、验证和完成标准字段。"""
    step = _rule_step(
        title="创建配置文件",
        description="在 configs 下创建配置。",
        expected_output="配置文件存在。",
        verification="检查配置文件路径。",
        completion_criteria="配置文件存在且非空。",
    )

    for field_name in ("title", "description", "expected_output", "verification", "completion_criteria"):
        assert step[field_name]


def test_skill_resolver_state_is_exposed_for_legacy_bridge() -> None:
    """摘要：拆解后保留最近一次 Skill 名称和阶段，兼容旧 HTTP 桥接读取。"""
    decomposer = PlanDecomposer(
        skill_resolver=lambda user_input: ("coding-agent", ["brainstorming", "planning", "tdd"])
    )

    steps = decomposer.decide("实现任务拆解")

    assert steps
    assert decomposer.skill_name == "coding-agent"
    assert decomposer.skill_stages == ["brainstorming", "planning", "tdd"]


def test_rule_decompose_default_steps_are_structured() -> None:
    """摘要：默认规则 fallback 不再生成元模板步骤。"""
    steps = rule_decompose("帮我处理这个事情")
    combined = "\n".join(str(step.get("title", "")) for step in steps)

    assert len(steps) == 4
    assert "执行核心步骤" not in combined
    assert "验证与收尾" not in combined
