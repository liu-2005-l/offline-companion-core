from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from offline_companion.core.decomposition_result import NotDecomposableResult
from offline_companion.core.decomposition_sample_library import SampleShot
from offline_companion.core.llm_decomposer import (
    DECOMPOSE_SYSTEM_PROMPT,
    _align_stages,
    _parse_json,
    _validate_steps,
    decompose_with_llm,
)
from offline_companion.core.plan_orchestrator import InMemoryPlanStore, PlanOrchestrator


def _valid_step() -> dict[str, object]:
    return {
        "title": "创建 utils.py",
        "description": "在 src 下创建工具模块。",
        "expected_output": "src/utils.py 文件存在。",
        "verification": "检查 src/utils.py 是否存在。",
        "completion_criteria": "文件存在且内容可导入。",
        "stage": "tdd",
        "estimated_minutes": 5,
        "files": ["src/utils.py"],
    }


def _valid_response() -> str:
    return """[
        {
            "title": "创建 sort.py",
            "description": "实现快速排序函数。",
            "expected_output": "src/sort.py 文件存在且包含 quick_sort。",
            "verification": "python -m pytest tests/test_sort.py",
            "completion_criteria": "排序测试全绿。",
            "stage": "tdd",
            "estimated_minutes": 15,
            "files": ["src/sort.py"]
        }
    ]"""


def test_parse_json_plain_array() -> None:
    result = _parse_json('[{"title": "test", "description": "d"}]')

    assert result is not None
    assert result[0]["title"] == "test"


def test_parse_json_code_fence() -> None:
    result = _parse_json('```json\n[{"title": "test"}]\n```')

    assert result is not None
    assert len(result) == 1


def test_parse_json_surrounding_text() -> None:
    result = _parse_json('Here is the plan:\n[{"title": "test"}]\nDone.')

    assert result is not None
    assert len(result) == 1


def test_parse_json_invalid_values_return_none() -> None:
    assert _parse_json("not json at all") is None
    assert _parse_json("[]") is None
    assert _parse_json('{"title": "test"}') is None


def test_validate_steps_accepts_complete_step() -> None:
    assert _validate_steps([_valid_step()]) is True


def test_validate_steps_rejects_missing_or_empty_field() -> None:
    missing = _valid_step()
    del missing["expected_output"]
    empty = _valid_step()
    empty["title"] = "  "

    assert _validate_steps([missing]) is False
    assert _validate_steps([empty]) is False


def test_validate_steps_rejects_meta_patterns() -> None:
    title_meta = _valid_step()
    title_meta["title"] = "执行核心步骤"
    description_meta = _valid_step()
    description_meta["description"] = "理解目标然后制定方案。"

    assert _validate_steps([title_meta]) is False
    assert _validate_steps([description_meta]) is False


def test_align_stages_accepts_valid_or_empty_stages() -> None:
    stages = ["brainstorming", "planning", "tdd", "review", "finalize"]

    assert _align_stages([{"stage": "brainstorming"}], stages) is not None
    assert _align_stages([{"stage": ""}], stages) is not None
    assert _align_stages([{"stage": "anything"}], []) is not None
    assert _align_stages([{"stage": "anything"}], None) is not None


def test_align_stages_rejects_unknown_stage() -> None:
    result = _align_stages([{"stage": "unknown_phase"}], ["brainstorming"])

    assert result is None


def test_decompose_with_llm_success() -> None:
    backend = MagicMock()
    backend.chat.return_value = _valid_response()

    result = decompose_with_llm("写一个排序算法", backend)

    assert result is not None
    assert result[0]["title"] == "创建 sort.py"
    assert result[0]["expected_output"] == "src/sort.py 文件存在且包含 quick_sort。"


def test_decompose_with_llm_none_returns_semantic_result() -> None:
    backend = MagicMock()
    backend.chat.return_value = "  NONE\n"

    result = decompose_with_llm("你最近怎么样", backend)

    assert result == NotDecomposableResult(reason="model_none", original_input="你最近怎么样")


def test_decompose_without_shots_keeps_prompts_byte_identical() -> None:
    backend = MagicMock()
    backend.chat.return_value = _valid_response()

    decompose_with_llm("写一个排序算法", backend, shots=None)
    none_call = backend.chat.call_args.kwargs
    backend.reset_mock()
    backend.chat.return_value = _valid_response()
    decompose_with_llm("写一个排序算法", backend, shots=[])
    empty_call = backend.chat.call_args.kwargs

    assert none_call["system_prompt"] == DECOMPOSE_SYSTEM_PROMPT
    assert empty_call["system_prompt"] == DECOMPOSE_SYSTEM_PROMPT
    assert none_call["user_prompt"] == "用户请求：写一个排序算法\n\n请拆解为具体步骤，返回 JSON 数组。"
    assert empty_call["user_prompt"] == none_call["user_prompt"]


def test_decompose_prompt_has_none_exit_without_single_utils_anchor() -> None:
    assert "只输出 none" in DECOMPOSE_SYSTEM_PROMPT
    assert "只返回 JSON 数组或 none" in DECOMPOSE_SYSTEM_PROMPT
    assert "“你擅长什么” → none" in DECOMPOSE_SYSTEM_PROMPT
    assert "“你能做什么” → none" in DECOMPOSE_SYSTEM_PROMPT
    assert "“给我讲讲CRC码” → none" in DECOMPOSE_SYSTEM_PROMPT
    assert "“什么是RSA加密” → none" in DECOMPOSE_SYSTEM_PROMPT
    assert "“讲讲CRC码的原理” → none" in DECOMPOSE_SYSTEM_PROMPT
    assert "“写一个排序算法并保存” → 按下方格式输出 JSON 数组" in DECOMPOSE_SYSTEM_PROMPT
    assert "步骤描述不得复述用户原话" in DECOMPOSE_SYSTEM_PROMPT
    assert "utils.py" not in DECOMPOSE_SYSTEM_PROMPT


def test_decompose_shots_only_extend_single_decompose_system_prompt() -> None:
    backend = MagicMock(spec=["generate"])
    backend.generate.return_value = _valid_response()
    shot = SampleShot(
        sample_id="7",
        task_description="实现本地排序",
        steps=({"title": "创建模块", "description": "实现排序", "verification": "跑测试", "expected_output": "模块"},),
        similarity=0.8,
        score=0.7,
        tool_refs=("python",),
        token_count=20,
    )

    decompose_with_llm("写一个排序算法", backend, shots=[shot])

    kwargs = backend.generate.call_args.kwargs
    assert kwargs["system_prompt"].startswith(DECOMPOSE_SYSTEM_PROMPT)
    assert "[任务拆解范例]" in kwargs["system_prompt"]
    assert "实现本地排序" in kwargs["system_prompt"]
    assert kwargs["history"] == []
    assert kwargs["memory_block"] == ""
    assert kwargs["user_message"] == "用户请求：写一个排序算法\n\n请拆解为具体步骤，返回 JSON 数组。"


def test_decompose_with_llm_exception_or_invalid_output_returns_none() -> None:
    failing_backend = MagicMock()
    failing_backend.chat.side_effect = RuntimeError("no model")
    invalid_backend = MagicMock()
    invalid_backend.chat.return_value = "not json"

    assert decompose_with_llm("test", failing_backend) is None
    assert decompose_with_llm("test", invalid_backend) is None
    assert decompose_with_llm("test", None) is None


def test_decompose_with_llm_rejects_meta_or_missing_fields() -> None:
    meta_backend = MagicMock()
    meta_backend.chat.return_value = """[
        {
            "title": "执行核心步骤",
            "description": "执行。",
            "expected_output": "something",
            "verification": "check",
            "completion_criteria": "done"
        }
    ]"""
    missing_backend = MagicMock()
    missing_backend.chat.return_value = '[{"title": "创建文件", "description": "创建。"}]'

    assert decompose_with_llm("test", meta_backend) is None
    assert decompose_with_llm("test", missing_backend) is None


def test_decompose_with_llm_injects_skill_stage_hint() -> None:
    backend = MagicMock()
    backend.chat.return_value = _valid_response()

    decompose_with_llm(
        "test",
        backend,
        skill_stages=["brainstorming", "planning", "tdd", "review", "finalize"],
        skill_name="coding-agent",
    )

    user_prompt = backend.chat.call_args.kwargs["user_prompt"]
    assert "brainstorming" in user_prompt
    assert "coding-agent" in user_prompt


def test_plan_orchestrator_decide_uses_llm_when_available() -> None:
    backend = MagicMock()
    backend.chat.return_value = _valid_response()
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), llm_backend=backend)

    steps = orchestrator.decide("写一个排序算法")

    assert len(steps) == 1
    assert steps[0].title == "创建 sort.py"
    assert steps[0].expected_output
    assert steps[0].payload["description"] == steps[0].title
    assert steps[0].files == ("src/sort.py",)


def test_plan_orchestrator_decide_fallbacks_when_llm_fails() -> None:
    backend = MagicMock()
    backend.chat.side_effect = RuntimeError("no model")
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), llm_backend=backend)

    steps = orchestrator.decide("写一个 CSV 处理脚本")

    assert len(steps) == 5
    assert all(step.title for step in steps)
    assert all(step.expected_output for step in steps)
    assert all(step.verification for step in steps)
    assert all("执行核心步骤" not in step.title for step in steps)


def test_plan_context_persists_decomposition_provenance_and_candidate() -> None:
    backend = MagicMock()
    backend.chat.return_value = _valid_response()
    retriever = MagicMock()
    retriever.retrieve.return_value = [
        SampleShot("41", "历史任务", (), 0.8, 0.7, (), 10)
    ]
    lifecycle = MagicMock()
    lifecycle.create_candidate.return_value = SimpleNamespace(sample_id="42")
    orchestrator = PlanOrchestrator(
        InMemoryPlanStore(),
        llm_backend=backend,
        sample_retriever=retriever,
        sample_lifecycle=lifecycle,
    )

    steps = orchestrator.decide("写一个排序算法")
    context = orchestrator.create_plan("plan_42", steps)

    assert context.context_vars["decomposition"] == {
        "source": "llm",
        "sample_ids": ["41"],
        "candidate_sample_id": "42",
    }
    lifecycle.assign_plan_id.assert_called_once_with("42", "plan_42")


def test_plan_orchestrator_decide_without_llm_uses_rules() -> None:
    orchestrator = PlanOrchestrator(InMemoryPlanStore())

    steps = orchestrator.decide("分析项目架构")

    assert len(steps) == 3
    assert all(step.title and step.expected_output for step in steps)
