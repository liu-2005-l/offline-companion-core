from __future__ import annotations

from offline_companion.core.plan_orchestrator import (
    PlanStatus,
    PlanStep,
    StepStatus,
    TaskContext,
)
from offline_companion.shell.plan_final_reply import aggregate_step_results, build_final_reply


def _context(status: PlanStatus) -> TaskContext:
    first = PlanStep("step-1", "chat", "step-1-result", payload={}, title="分析")
    second = PlanStep("step-2", "chat", "step-2-result", payload={}, title="执行")
    return TaskContext(
        plan_id="plan-final-reply",
        status=status,
        steps={first.step_id: first, second.step_id: second},
        step_status={first.step_id: StepStatus.DONE, second.step_id: StepStatus.FAILED},
        step_results={first.result_key: {"result": "分析完成"}},
        step_errors={second.step_id: "执行失败"},
        context_vars={"manual_plan": {"goal": "完成任务"}},
    )


def test_build_final_reply_uses_summarizer_for_done_and_failed() -> None:
    prompts: list[str] = []

    def summarize(prompt: str) -> str:
        prompts.append(prompt)
        return "这是统一的最终总结。"

    done = _context(PlanStatus.DONE)
    failed = _context(PlanStatus.FAILED)

    assert build_final_reply(done, summarizer=summarize) == "这是统一的最终总结。"
    assert build_final_reply(failed, summarizer=summarize) == "这是统一的最终总结。"
    assert len(prompts) == 2
    assert all("完成任务" in prompt and "步骤结果" in prompt for prompt in prompts)


def test_build_final_reply_falls_back_without_swallowing_results() -> None:
    context = _context(PlanStatus.DONE)

    def fail_summary(_prompt: str) -> str:
        raise RuntimeError("model unavailable")

    reply = build_final_reply(context, summarizer=fail_summary)

    assert reply is not None
    assert "任务已完成，完成 1/2 步骤" in reply
    assert "分析完成" in reply


def test_build_final_reply_cancelled_is_deterministic_without_llm() -> None:
    calls: list[str] = []
    context = _context(PlanStatus.CANCELLED)

    reply = build_final_reply(context, summarizer=lambda prompt: calls.append(prompt) or "不应调用")

    assert reply == "任务已取消，完成 1/2 步骤。"
    assert calls == []


def test_build_final_reply_blocked_and_non_terminal_are_empty() -> None:
    blocked = _context(PlanStatus.FAILED)
    blocked.plan_status = "blocked"
    running = _context(PlanStatus.RUNNING)

    assert build_final_reply(blocked, summarizer=lambda _prompt: "不应生成") is None
    assert build_final_reply(running, summarizer=lambda _prompt: "不应生成") is None


def test_legacy_auto_aggregation_remains_byte_equivalent() -> None:
    context = _context(PlanStatus.DONE)

    assert aggregate_step_results(context) == "分析完成"
    assert build_final_reply(context) == "分析完成"


def test_final_reply_retries_arithmetic_once_and_rechecks_new_reply() -> None:
    context = _context(PlanStatus.DONE)
    replies = iter(("计算结果为 7×3=77。", "重新核算后 7×3=21。"))
    prompts: list[str] = []

    def summarize(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies)

    reply = build_final_reply(context, summarizer=summarize)

    assert reply == "重新核算后 7×3=21。"
    assert len(prompts) == 2
    assert "【算术校验反馈】" in prompts[1]
    assert "正确值 21" in prompts[1]


def test_final_reply_uses_warning_when_quality_retry_was_consumed() -> None:
    context = _context(PlanStatus.DONE)
    context.quality_retry_counts = {"step-1": 1}
    prompts: list[str] = []

    reply = build_final_reply(
        context,
        summarizer=lambda prompt: prompts.append(prompt) or "计算结果为 7×3=77。",
    )

    assert len(prompts) == 1
    assert reply is not None
    assert "机械计算结果为 21" in reply


def test_final_reply_retries_copular_arithmetic_statement() -> None:
    """摘要：计划终态中的“算式结果是数字”必须进入同一审计重试。"""

    context = _context(PlanStatus.DONE)
    replies = iter(("3乘7的结果是14。", "重新核算后，3乘7的结果是21。"))

    reply = build_final_reply(context, summarizer=lambda _prompt: next(replies))

    assert reply == "重新核算后，3乘7的结果是21。"
