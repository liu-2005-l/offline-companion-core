"""摘要：定义任务拆解的语义化返回结果。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class NotDecomposableResult:
    """摘要：表示输入不应进入计划拆解和留档链路。

    参数：
        reason: 不可拆解原因。
        original_input: 用户提交的原始输入。
        status: 固定的语义状态标识。
        fallback_notice: 降级普通对话前需要向用户展示的确定性提示。
        status: 固定的语义状态标识。
        fallback_notice: 降级普通对话前需要向用户展示的确定性提示。
    """

    reason: Literal[
        "greeting",
        "model_none",
        "low_relevance",
        "echo",
        "meta_template",
        "explanation",
        "no_rule_match",
        "method_constraint_lost",
        "zero_value_plan",
    ]
    original_input: str
    status: Literal["not_decomposable"] = "not_decomposable"
    fallback_notice: str | None = None
