"""arithmetic_verifier：机械提取并校验回复中的显式算术断言。"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext

logger = logging.getLogger(__name__)

_NUMBER = r"[+\-−]?\d+(?:\.\d+)?"
_OPERATOR = r"(?:除以|乘以|\*\*|[×xX*乘+加\-−减÷/^])"
_EQUALITY = r"(?:=|等于|(?:的结果|的答案|的积|的和)?是)"
_OPERATOR_CHARACTERS = "×xX*乘+加-−减÷/^"
_ASSERTION_PATTERN = re.compile(
    rf"(?<![\w.{re.escape(_OPERATOR_CHARACTERS)}])"
    rf"(?P<left>{_NUMBER})\s*(?P<operator>{_OPERATOR})\s*"
    rf"(?P<right>{_NUMBER})\s*(?P<equality>{_EQUALITY})\s*"
    rf"(?P<claimed>{_NUMBER})(?![\w.])"
)
_NUMBER_PATTERN = re.compile(_NUMBER)
_NEGATION_WORDS = (
    "无稽之谈",
    "不正确",
    "不成立",
    "误以为",
    "错误",
    "不对",
    "并非",
    "不是",
    "有误",
    "误区",
    "谬论",
    "错",
    "≠",
)
_QUOTE_PAIRS = {"'": "'", '"': '"', "“": "”", "‘": "’", "「": "」"}
_OPERATOR_ALIASES = {
    "×": "multiply",
    "x": "multiply",
    "X": "multiply",
    "*": "multiply",
    "乘": "multiply",
    "乘以": "multiply",
    "+": "add",
    "加": "add",
    "-": "subtract",
    "−": "subtract",
    "减": "subtract",
    "÷": "divide",
    "/": "divide",
    "除以": "divide",
    "^": "power",
    "**": "power",
}


@dataclass(frozen=True)
class ArithmeticAssertion:
    """摘要：一条可机械计算的显式算术断言。"""

    expression: str
    left: Decimal
    operator: str
    right: Decimal
    claimed: Decimal
    expected: Decimal


@dataclass(frozen=True)
class ArithmeticAuditResult:
    """摘要：回复算术审计结果及最终可展示正文。"""

    reply: str
    failures: tuple[ArithmeticAssertion, ...]
    retried: bool = False


def extract_arithmetic_assertions(text: str) -> tuple[ArithmeticAssertion, ...]:
    """摘要：提取可安全判定的十进制四则与整数幂断言。

    参数：
        text: 待检查的模型回复。

    返回值：
        可机械计算的断言；引用、否定及非常规字面量会被跳过。
    """
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    if not _has_arithmetic_candidate(normalized):
        return ()
    assertions: list[ArithmeticAssertion] = []
    for match in _iter_assertion_matches(normalized):
        if _is_quoted(normalized, match.start(), match.end()):
            continue
        context = normalized[max(0, match.start() - 12) : min(len(normalized), match.end() + 12)]
        if any(word in context for word in _NEGATION_WORDS):
            continue
        assertion = _build_assertion(match)
        if assertion is not None:
            assertions.append(assertion)
    return tuple(assertions)


def invalid_arithmetic_assertions(text: str) -> tuple[ArithmeticAssertion, ...]:
    """摘要：返回计算结果与模型声称结果不匹配的断言。"""
    return _invalid_assertions(extract_arithmetic_assertions(text))


def audit_arithmetic_reply(
    reply: str,
    *,
    retry: Callable[[str], str] | None = None,
    retry_allowed: bool = True,
) -> ArithmeticAuditResult:
    """摘要：审计回复，必要时重试一次或追加确定性警示。

    参数：
        reply: 首次模型回复。
        retry: 接收系统反馈并重新生成回复的回调。
        retry_allowed: 是否仍有质量重试槽位。

    返回值：
        最终展示正文、剩余失败断言与是否发生重试。
    """
    original = str(reply or "")
    normalized = unicodedata.normalize("NFKC", original)
    skip_reason = _arithmetic_candidate_skip_reason(normalized)
    assertions = () if skip_reason is not None else extract_arithmetic_assertions(normalized)
    failures = _invalid_assertions(assertions)
    logger.info(
        "算术断言审计完成: extracted=%d failures=%d retry_allowed=%s skipped=%s",
        len(assertions),
        len(failures),
        retry_allowed,
        skip_reason or "none",
    )
    if not failures:
        return ArithmeticAuditResult(reply=original, failures=())
    if retry is not None and retry_allowed:
        try:
            retried_reply = str(retry(build_arithmetic_feedback(failures)) or "").strip()
        except Exception:
            logger.warning("算术断言修正重试失败，降级为确定性警示", exc_info=True)
            retried_reply = ""
        if retried_reply:
            normalized_retry = unicodedata.normalize("NFKC", retried_reply)
            retry_skip_reason = _arithmetic_candidate_skip_reason(normalized_retry)
            retry_assertions = (
                ()
                if retry_skip_reason is not None
                else extract_arithmetic_assertions(normalized_retry)
            )
            retry_failures = _invalid_assertions(retry_assertions)
            logger.info(
                "算术断言重试审计完成: extracted=%d failures=%d skipped=%s",
                len(retry_assertions),
                len(retry_failures),
                retry_skip_reason or "none",
            )
            if not retry_failures:
                return ArithmeticAuditResult(reply=retried_reply, failures=(), retried=True)
            return ArithmeticAuditResult(
                reply=_append_warning(retried_reply, retry_failures),
                failures=retry_failures,
                retried=True,
            )
    return ArithmeticAuditResult(reply=_append_warning(original, failures), failures=failures)


def build_arithmetic_feedback(failures: tuple[ArithmeticAssertion, ...]) -> str:
    """摘要：构造供单次重试使用的系统提示尾注。"""
    details = "；".join(
        f"{item.expression}（正确值 {_format_decimal(item.expected)}）" for item in failures
    )
    return f"你上次的回复包含错误算术断言：{details}。请修正后重新回答。"


def _invalid_assertions(
    assertions: tuple[ArithmeticAssertion, ...],
) -> tuple[ArithmeticAssertion, ...]:
    """摘要：从已提取断言中过滤机械计算不匹配项。"""
    return tuple(
        assertion
        for assertion in assertions
        if not _numbers_match(assertion.expected, assertion.claimed)
    )


def _iter_assertion_matches(text: str):
    """摘要：隔离正则遍历，便于验证快路径不会启动提取器。"""
    return _ASSERTION_PATTERN.finditer(text)


def _has_arithmetic_candidate(text: str) -> bool:
    """摘要：以低成本信号排除绝大多数普通中文回复。"""
    return _arithmetic_candidate_skip_reason(text) is None


def _arithmetic_candidate_skip_reason(text: str) -> str | None:
    """摘要：返回算术审计快路径跳过原因，供诊断日志复用。"""
    if "=" not in text and "等于" not in text and "是" not in text:
        return "missing_equality"
    if not any(marker in text for marker in _OPERATOR_ALIASES):
        return "missing_operator"
    if len(_NUMBER_PATTERN.findall(text)) < 3:
        return "insufficient_numbers"
    return None


def _build_assertion(match: re.Match[str]) -> ArithmeticAssertion | None:
    try:
        left = Decimal(match.group("left").replace("−", "-"))
        right = Decimal(match.group("right").replace("−", "-"))
        claimed = Decimal(match.group("claimed").replace("−", "-"))
        operator = _OPERATOR_ALIASES[match.group("operator")]
        expected = _calculate(left, operator, right)
    except (DecimalException, KeyError, OverflowError, ValueError, ZeroDivisionError):
        return None
    return ArithmeticAssertion(
        expression=match.group(0).strip(),
        left=left,
        operator=operator,
        right=right,
        claimed=claimed,
        expected=expected,
    )


def _calculate(left: Decimal, operator: str, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 64
        if operator == "multiply":
            return left * right
        if operator == "add":
            return left + right
        if operator == "subtract":
            return left - right
        if operator == "divide":
            return left / right
        if operator == "power":
            if right != right.to_integral_value() or abs(right) > 1000:
                raise ValueError("unsupported decimal exponent")
            return left**int(right)
    raise ValueError(f"unsupported arithmetic operator: {operator}")


def _numbers_match(expected: Decimal, claimed: Decimal) -> bool:
    if claimed == claimed.to_integral_value():
        return expected == claimed
    quantum = Decimal(1).scaleb(claimed.as_tuple().exponent)
    try:
        return expected.quantize(quantum) == claimed
    except DecimalException:
        return False


def _is_quoted(text: str, start: int, end: int) -> bool:
    left_index = start - 1
    while left_index >= 0 and text[left_index].isspace():
        left_index -= 1
    right_index = end
    while right_index < len(text) and text[right_index].isspace():
        right_index += 1
    if left_index < 0 or right_index >= len(text):
        return False
    return _QUOTE_PAIRS.get(text[left_index]) == text[right_index]


def _append_warning(reply: str, failures: tuple[ArithmeticAssertion, ...]) -> str:
    lines = [
        f"「{item.expression}」，机械计算结果为 {_format_decimal(item.expected)}"
        for item in failures
    ]
    detail = "；".join(lines)
    warning = f"⚠ 自动校验：上文有 {len(failures)} 处算术断言与计算结果不符——{detail}。"
    return f"{reply.rstrip()}\n\n{warning}"


def _format_decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return format(value.quantize(Decimal(1)), "f")
    return format(value.normalize(), "f")
