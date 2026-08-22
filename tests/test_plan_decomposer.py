from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from offline_companion.core.decomposition_result import NotDecomposableResult
from offline_companion.core.decomposition_sample_library import SampleShot
from offline_companion.core.llm_decomposer import DECOMPOSE_SYSTEM_PROMPT
from offline_companion.core.plan_decomposer import (
    PlanDecomposer,
    _detect_echo,
    _extract_method_constraints,
    _is_explanation_request,
    _rule_step,
    _zero_value_plan_score,
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


@pytest.mark.parametrize(
    "text",
    [
        "你好",
        "！您好。",
        "hello",
        "好的",
        "谢谢！",
        "你擅长什么",
        "你能做什么",
        "你会什么",
        "你会做什么",
        "你能干嘛",
        "介绍一下你自己",
        "介绍你自己",
        "你叫什么",
        "你叫什么名字",
        "你是谁",
    ],
)
def test_non_task_exact_match_skips_retrieval_and_candidate_archive(text: str) -> None:
    retriever = MagicMock()
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(sample_retriever=retriever, sample_lifecycle=lifecycle)

    result = decomposer.decide(text)

    assert result == NotDecomposableResult(reason="greeting", original_input=text)
    retriever.retrieve.assert_not_called()
    lifecycle.create_candidate.assert_not_called()


def test_non_task_gate_does_not_use_contains_or_length_rules() -> None:
    backend = MagicMock()
    backend.chat.side_effect = [
        """[{
            "title":"创建排序模块",
            "description":"为用户请求实现排序算法并保存结果",
            "expected_output":"可用的排序模块",
            "verification":"运行排序测试",
            "completion_criteria":"排序测试通过"
        }]""",
        """[{
            "title":"修复 bug",
            "description":"定位并修复 bug",
            "expected_output":"bug 已修复",
            "verification":"运行相关测试",
            "completion_criteria":"测试通过且 bug 不再复现"
        }]""",
    ]
    decomposer = PlanDecomposer(llm_router=backend)

    contained = decomposer.decide("你好，帮我写个排序并保存")
    short_task = decomposer.decide("修下bug")

    assert isinstance(contained, list)
    assert short_task == NotDecomposableResult(
        reason="zero_value_plan",
        original_input="修下bug",
        fallback_notice="该计划没有增加可执行步骤，已转为直接回答。",
    )
    assert backend.chat.call_count == 2


def test_low_relevance_steps_are_rejected_before_candidate_archive() -> None:
    backend = MagicMock()
    backend.chat.return_value = """[{
        "title":"在 src 下创建 utils.py",
        "description":"创建 Python 工具文件",
        "expected_output":"utils.py 文件",
        "verification":"检查文件存在",
        "completion_criteria":"文件可以导入"
    }]"""
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend, sample_lifecycle=lifecycle)

    result = decomposer.decide("今天心情怎么样")

    assert result == NotDecomposableResult(reason="low_relevance", original_input="今天心情怎么样")
    lifecycle.create_candidate.assert_not_called()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("按booth算法计算7乘3", ("booth算法",)),
        ("按照快速排序算法整理数据", ("快速排序算法",)),
        ("使用 UTF-8 格式保存文件", ("utf8格式",)),
        ("用HTTP协议发送请求", ("http协议",)),
        ("通过 CRC 协议校验数据", ("crc协议",)),
    ],
)
def test_extract_method_constraints(text: str, expected: tuple[str, ...]) -> None:
    assert _extract_method_constraints(text) == expected


def test_method_constraint_loss_retries_once_and_preserves_constraint() -> None:
    backend = MagicMock()
    backend.chat.side_effect = [
        """[{
            "title":"排序数据",
            "description":"执行排序",
            "expected_output":"排序结果",
            "verification":"核对排序结果",
            "completion_criteria":"排序完成"
        }]""",
        """[
        {
            "title":"使用快速排序算法整理数据",
            "description":"按快速排序算法执行分区和递归",
            "expected_output":"快速排序算法中间状态",
            "verification":"核对快速排序算法分区结果",
            "completion_criteria":"排序步骤完整"
        },
        {
            "title":"核对快速排序算法结果",
            "description":"根据分区状态核对最终顺序",
            "expected_output":"经核对的排序结果",
            "verification":"复核最终顺序",
            "completion_criteria":"算法步骤与结果一致"
        }
        ]""",
    ]
    decomposer = PlanDecomposer(llm_router=backend)

    result = decomposer.decide("按快速排序算法整理数据")

    assert isinstance(result, list)
    assert len(result) == 2
    assert "快速排序算法" in result[0].title
    assert backend.chat.call_count == 2
    assert "必须在至少一个步骤中明确保留这些方法约束：快速排序算法" in (
        backend.chat.call_args.kwargs["user_prompt"]
    )


def test_booth_method_uses_builtin_tool_plan_without_llm() -> None:
    backend = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend)

    result = decomposer.decide("按booth算法计算7乘3")

    assert isinstance(result, list)
    assert [step.skill_id for step in result] == ["algorithm_booth", "chat"]
    assert result[0].payload["tool_args"] == {"multiplicand": 7, "multiplier": 3}
    assert result[1].depends_on == ("booth_tool",)
    backend.chat.assert_not_called()


def test_calculator_method_uses_builtin_tool_plan_without_llm() -> None:
    backend = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend)

    result = decomposer.decide("请计算三乘七")

    assert isinstance(result, list)
    assert [step.skill_id for step in result] == ["calculator", "chat"]
    assert result[0].payload["tool_args"] == {"left": "三", "operator": "乘", "right": "七"}
    assert result[1].depends_on == ("calculator_tool",)
    backend.chat.assert_not_called()


def test_method_constraint_loss_falls_back_without_candidate_archive() -> None:
    backend = MagicMock()
    backend.chat.return_value = """[{
        "title":"排序数据",
        "description":"执行排序",
        "expected_output":"排序结果",
        "verification":"核对排序结果",
        "completion_criteria":"排序完成"
    }]"""
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend, sample_lifecycle=lifecycle)

    result = decomposer.decide("按快速排序算法整理数据")

    assert result == NotDecomposableResult(
        reason="method_constraint_lost",
        original_input="按快速排序算法整理数据",
        fallback_notice="无法按指定方法分步执行，已转为直接回答；本地模型可能无法严格复现该方法。",
    )
    assert backend.chat.call_count == 2
    lifecycle.create_candidate.assert_not_called()


def test_zero_value_single_chat_plan_falls_back_without_candidate_archive() -> None:
    backend = MagicMock()
    backend.chat.return_value = """[{
        "title":"处理这个事情",
        "description":"处理用户请求并返回结果",
        "expected_output":"处理结果",
        "verification":"核对处理结果",
        "completion_criteria":"得到正确结果"
    }]"""
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend, sample_lifecycle=lifecycle)

    result = decomposer.decide("请帮我处理一下这个事情")

    assert result == NotDecomposableResult(
        reason="zero_value_plan",
        original_input="请帮我处理一下这个事情",
        fallback_notice="该计划没有增加可执行步骤，已转为直接回答。",
    )
    lifecycle.create_candidate.assert_not_called()


def test_method_preserved_zero_value_plan_uses_method_limitation_notice() -> None:
    backend = MagicMock()
    backend.chat.return_value = """[{
        "title":"使用快速排序算法整理数据",
        "description":"使用快速排序算法整理数据",
        "expected_output":"快速排序算法结果",
        "verification":"核对快速排序算法结果",
        "completion_criteria":"得到结果"
    }]"""
    decomposer = PlanDecomposer(llm_router=backend)

    result = decomposer.decide("按快速排序算法整理数据")

    assert result == NotDecomposableResult(
        reason="zero_value_plan",
        original_input="按快速排序算法整理数据",
        fallback_notice="无法按指定方法分步执行，已转为直接回答；本地模型可能无法严格复现该方法。",
    )


def test_zero_value_check_ignores_multi_step_and_non_chat_plans() -> None:
    chat_step = raw_to_plan_step(_valid_raw_step(), "写排序算法", 0)
    second_step = raw_to_plan_step(_valid_raw_step(), "写排序算法", 1)
    tool_step = raw_to_plan_step(
        {**_valid_raw_step(), "skill_id": "calculator", "title": "计算7乘3"},
        "计算7乘3",
        0,
    )

    assert _zero_value_plan_score("创建 sort.py", [chat_step, second_step]) is None
    assert _zero_value_plan_score("计算7乘3", [tool_step]) is None


def test_unrelated_generated_steps_fall_back_to_chat() -> None:
    backend = MagicMock()
    backend.chat.return_value = """[{
        "title":"汇总服务器日志",
        "description":"收集磁盘告警并定位异常进程",
        "expected_output":"日志报告",
        "verification":"核对告警记录",
        "completion_criteria":"异常进程已定位"
    }]"""
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend, sample_lifecycle=lifecycle)

    result = decomposer.decide("说明你的主要能力范围")

    assert result == NotDecomposableResult(
        reason="low_relevance",
        original_input="说明你的主要能力范围",
    )
    lifecycle.create_candidate.assert_not_called()


def test_echoed_capability_question_is_rejected_before_candidate_archive() -> None:
    backend = MagicMock()
    backend.chat.return_value = """[{
        "title":"brainstorming",
        "description":"用户请求：说明你的主要能力范围",
        "expected_output":"用户请求：说明你的主要能力范围",
        "verification":"确认用户请求是否为具体任务",
        "completion_criteria":"用户请求已明确"
    }]"""
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend, sample_lifecycle=lifecycle)

    result = decomposer.decide("说明你的主要能力范围")

    assert result == NotDecomposableResult(
        reason="echo",
        original_input="说明你的主要能力范围",
    )
    lifecycle.create_candidate.assert_not_called()


def test_echo_detection_distinguishes_full_sentence_from_shared_terms() -> None:
    assert _detect_echo("你擅长什么", "brainstorming", ["用户请求：你擅长什么"])
    assert _detect_echo("你擅长什么", "围绕你擅长什么生成任务", [])
    assert not _detect_echo("写排序算法并保存", "", ["创建 sort.py 实现排序算法"])
    assert not _detect_echo("你好", "", ["用户说你好"])


def test_explanation_request_falls_back_before_model_and_candidate_archive() -> None:
    backend = MagicMock()
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend, sample_lifecycle=lifecycle)

    result = decomposer.decide("给我讲讲CRC码")

    assert result == NotDecomposableResult(
        reason="explanation",
        original_input="给我讲讲CRC码",
    )
    backend.chat.assert_not_called()
    lifecycle.create_candidate.assert_not_called()


def test_multiple_scaffold_title_variants_are_rejected() -> None:
    backend = MagicMock()
    backend.chat.return_value = """[
      {"title":"确认任务边界：提取目标对象和约束","description":"梳理范围","expected_output":"边界","verification":"检查边界","completion_criteria":"边界明确"},
      {"title":"拆出可执行动作：形成最小步骤清单","description":"列出动作","expected_output":"清单","verification":"检查清单","completion_criteria":"清单完整"}
    ]"""
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend, sample_lifecycle=lifecycle)

    result = decomposer.decide("规划支付模块重构")

    assert result == NotDecomposableResult(
        reason="meta_template",
        original_input="规划支付模块重构",
    )
    lifecycle.create_candidate.assert_not_called()


def test_single_scaffold_title_match_does_not_block_real_task() -> None:
    backend = MagicMock()
    backend.chat.return_value = """[
      {"title":"确认任务边界：梳理支付模块约束","description":"梳理支付模块范围","expected_output":"支付模块边界","verification":"核对支付模块约束","completion_criteria":"支付模块边界明确"},
      {"title":"重构支付模块","description":"实现支付模块重构","expected_output":"重构后的支付模块","verification":"运行支付模块测试","completion_criteria":"支付模块测试通过"}
    ]"""
    decomposer = PlanDecomposer(llm_router=backend)

    result = decomposer.decide("重构支付模块并补齐测试")

    assert isinstance(result, list)
    assert len(result) == 2


def test_explanation_intent_wins_over_embedded_task_phrases() -> None:
    backend = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend)

    result = decomposer.decide("给我讲讲CRC码并整理成文档")

    assert result == NotDecomposableResult(
        reason="explanation",
        original_input="给我讲讲CRC码并整理成文档",
    )
    backend.chat.assert_not_called()


@pytest.mark.parametrize(
    ("text", "is_explanation"),
    [
        ("讲讲并发控制", True),
        ("什么是生成式AI", True),
        ("给我讲讲怎么写解析器", True),
        ("解释一下怎么写一个解析器", True),
        ("能详细讲讲吗，比如举个例子，怎么生成怎么计算", True),
        ("帮我写个排序", False),
        ("写一个CRC校验工具并保存", False),
        ("整理成 Markdown 导出", False),
        ("把这个保存下来", False),
    ],
)
def test_explanation_and_task_intent_precedence(text: str, is_explanation: bool) -> None:
    assert _is_explanation_request(text) is is_explanation


def test_rule_decompose_fallback() -> None:
    """摘要：LLM 不可用时规则 fallback 生成可用步骤。"""
    backend = MagicMock()
    backend.chat.side_effect = RuntimeError("no model")
    decomposer = PlanDecomposer(llm_router=backend)

    steps = decomposer.decide("写一个 CSV 处理脚本")

    assert len(steps) == 5
    assert all(step.title and step.completion_criteria for step in steps)
    assert all("执行核心步骤" not in step.title for step in steps)


def test_unmatched_rule_fallback_returns_chat_without_candidate_archive() -> None:
    backend = MagicMock()
    backend.chat.side_effect = RuntimeError("no model")
    lifecycle = MagicMock()
    decomposer = PlanDecomposer(llm_router=backend, sample_lifecycle=lifecycle)

    result = decomposer.decide("帮我处理这个事情")

    assert result == NotDecomposableResult(
        reason="no_rule_match",
        original_input="帮我处理这个事情",
    )
    lifecycle.create_candidate.assert_not_called()


def test_learning_disabled_skips_injection_but_keeps_candidate_archive() -> None:
    retriever = MagicMock()
    lifecycle = MagicMock()
    lifecycle.create_candidate.return_value = SimpleNamespace(sample_id="20")
    backend = MagicMock()
    backend.chat.return_value = """[{"title":"创建模块","description":"实现功能","expected_output":"模块","verification":"跑测试","completion_criteria":"测试通过"}]"""
    decomposer = PlanDecomposer(
        llm_router=backend,
        sample_retriever=retriever,
        sample_lifecycle=lifecycle,
        learning_enabled_provider=lambda: False,
    )

    assert decomposer.decide("实现本地脚本")

    retriever.retrieve.assert_not_called()
    lifecycle.create_candidate.assert_called_once()
    assert lifecycle.create_candidate.call_args.kwargs["provenance_sample_ids"] == []
    assert backend.chat.call_args.kwargs["system_prompt"] == DECOMPOSE_SYSTEM_PROMPT
    assert decomposer.last_sample_ids == []
    assert decomposer.last_candidate_sample_id == "20"


def test_llm_and_rule_decomposition_archive_source_and_provenance() -> None:
    shot = SampleShot("11", "历史任务", (), 0.8, 0.7, (), 10)
    retriever = MagicMock()
    retriever.retrieve.return_value = [shot]
    lifecycle = MagicMock()
    lifecycle.create_candidate.return_value = SimpleNamespace(sample_id="21")
    backend = MagicMock()
    backend.chat.return_value = "not json"
    decomposer = PlanDecomposer(
        llm_router=backend,
        sample_retriever=retriever,
        sample_lifecycle=lifecycle,
    )

    assert decomposer.decide("实现本地脚本")

    assert lifecycle.create_candidate.call_args.kwargs["source"] == "rule"
    assert lifecycle.create_candidate.call_args.kwargs["provenance_sample_ids"] == ["11"]
    assert decomposer.last_candidate_sample_id == "21"

    backend.chat.return_value = """[{"title":"创建模块","description":"实现功能","expected_output":"模块","verification":"跑测试","completion_criteria":"测试通过"}]"""
    lifecycle.create_candidate.return_value = SimpleNamespace(sample_id="22")
    assert decomposer.decide("实现另一个脚本")
    assert lifecycle.create_candidate.call_args.kwargs["source"] == "llm"


def test_bind_candidate_plan_backfills_assigned_plan_id() -> None:
    lifecycle = MagicMock()
    lifecycle.create_candidate.return_value = SimpleNamespace(sample_id="31")
    decomposer = PlanDecomposer(sample_lifecycle=lifecycle)
    decomposer.decide("实现本地脚本")

    decomposer.bind_candidate_plan("plan_31")

    lifecycle.assign_plan_id.assert_called_once_with("31", "plan_31")


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


def test_rule_decompose_unmatched_goal_has_no_generic_scaffold() -> None:
    """摘要：无领域匹配时不再生成通用脚手架。"""
    assert rule_decompose("帮我处理这个事情") is None
