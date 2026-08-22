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
    """

    reason: Literal[
        "greeting",
        "model_none",
        "low_relevance",
        "echo",
        "meta_template",
        "explanation",
        "no_rule_match",
    ]
    original_input: str
    status: Literal["not_decomposable"] = "not_decomposable"
