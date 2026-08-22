"""算术断言提取、验证与处置测试。"""

from __future__ import annotations

import logging

import pytest

from offline_companion.core import arithmetic_verifier
from offline_companion.core.arithmetic_verifier import (
    audit_arithmetic_reply,
    extract_arithmetic_assertions,
    invalid_arithmetic_assertions,
)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("7×3=21", "21"),
        ("7 x 3 等于 21", "21"),
        ("7乘以3=21", "21"),
        ("7乘3等于21", "21"),
        ("3乘7的结果是21", "21"),
        ("3乘7是21", "21"),
        ("0.1+0.2=0.3", "0.3"),
        ("3−7=−4", "-4"),
        ("７×３＝２１", "21"),
        ("3除以6=0.5", "0.5"),
        ("2**10=1024", "1024"),
    ],
)
def test_extract_supported_assertions(expression: str, expected: str) -> None:
    assertions = extract_arithmetic_assertions(expression)

    assert len(assertions) == 1
    assert str(assertions[0].expected) == expected


@pytest.mark.parametrize(
    "text",
    [
        "为什么 7×3=77 是错的",
        "你提到的 '7×3=77' 是什么含义",
        "你提到的“7×3=77”并不代表正确答案",
        "3除6=2",
        "3 = 11",
        "0xFF = 255",
        "x×2=10",
        "2^0.5=1.414",
        "5÷0=0",
        "3×7+1=22",
        "3乘7不是14",
        "3乘7很简单",
        "我说了3次，7是上限",
    ],
)
def test_extractor_skips_ambiguous_or_unsupported_context(text: str) -> None:
    assert extract_arithmetic_assertions(text) == ()


@pytest.mark.parametrize(
    ("expression", "invalid"),
    [
        ("10÷3=3", True),
        ("1÷3=0", True),
        ("6÷3=2", False),
        ("7×3=21", False),
        ("0.1+0.2=0.3", False),
        ("1÷3=0.33", False),
        ("1÷3=0.3333", False),
        ("1÷3=0.5", True),
        ("10^20=100000000000000000000", False),
        ("7×3=77", True),
        ("3乘7的结果是14", True),
    ],
)
def test_validation_uses_integer_exactness_and_decimal_precision(expression: str, invalid: bool) -> None:
    assert bool(invalid_arithmetic_assertions(expression)) is invalid


def test_fast_path_does_not_run_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(_text: str):
        raise AssertionError("regex should not run")

    monkeypatch.setattr(arithmetic_verifier, "_iter_assertion_matches", fail_if_called)

    assert extract_arithmetic_assertions("这是一段没有算术等式的普通回复") == ()


def test_audit_retries_with_feedback_and_returns_corrected_reply() -> None:
    feedback: list[str] = []

    result = audit_arithmetic_reply(
        "按照计算，7×3=77。",
        retry=lambda prompt: feedback.append(prompt) or "重新核算后，7×3=21。",
    )

    assert result.reply == "重新核算后，7×3=21。"
    assert result.retried is True
    assert result.failures == ()
    assert "正确值 21" in feedback[0]


def test_audit_warns_about_new_failure_from_retry() -> None:
    result = audit_arithmetic_reply(
        "7×3=77",
        retry=lambda _feedback: "7×3=21，但 2+2=5。",
    )

    assert "7×3=21" in result.reply
    assert "「2+2=5」" in result.reply
    assert "机械计算结果为 4" in result.reply
    assert len(result.failures) == 1


def test_audit_skips_retry_when_slot_is_unavailable() -> None:
    calls: list[str] = []

    result = audit_arithmetic_reply(
        "7×3=77",
        retry=lambda feedback: calls.append(feedback) or "7×3=21",
        retry_allowed=False,
    )

    assert calls == []
    assert result.retried is False
    assert "机械计算结果为 21" in result.reply


def test_audit_debug_log_records_extraction_count_without_reply_content(caplog) -> None:
    """摘要：调试日志记录提取计数，但不写入用户回复原文。"""

    with caplog.at_level(logging.DEBUG, logger="offline_companion.core.arithmetic_verifier"):
        audit_arithmetic_reply("3乘7的结果是14", retry_allowed=False)

    assert "extracted=1 failures=1" in caplog.text
    assert "3乘7的结果是14" not in caplog.text
