from __future__ import annotations

import zlib

import pytest

from offline_companion.core.algorithm_tools import (
    booth_multiply,
    crc32_utf8,
    euclidean_gcd,
    format_booth_result,
    format_crc32_result,
    format_gcd_result,
    format_quicksort_result,
    quicksort,
)


def test_booth_multiply_returns_deterministic_trace() -> None:
    trace = booth_multiply(7, 3)

    assert trace["algorithm"] == "booth"
    assert trace["result"] == 21
    assert trace["recoding"] == "3 = +4 -1"
    assert trace["partial_products"] == [28, -7]
    assert len(trace["rounds"]) == trace["bit_width"]
    assert trace["rounds"][0]["pair"] == "10"
    assert trace["rounds"][2]["pair"] == "01"
    rendered = format_booth_result(trace)
    assert "乘数重编码：3 = +4 -1" in rendered
    assert "部分积：28 - 7 = 21" in rendered
    assert "A = A - M" in rendered
    assert "A = A + M" in rendered
    assert "= 21" in rendered


@pytest.mark.parametrize(
    ("multiplicand", "multiplier"),
    [(0, 7), (7, 0), (3, 5), (-7, 3), (7, -3), (-7, -3)],
)
def test_booth_multiply_matches_integer_arithmetic(multiplicand: int, multiplier: int) -> None:
    assert booth_multiply(multiplicand, multiplier)["result"] == multiplicand * multiplier


def test_booth_multiply_rejects_boolean_operands() -> None:
    with pytest.raises(TypeError):
        booth_multiply(True, 3)


def test_crc32_utf8_returns_real_bit_trace_and_cross_checks_zlib() -> None:
    trace = crc32_utf8("abc")

    assert trace["algorithm"] == "crc32"
    assert trace["bytes"] == [97, 98, 99]
    assert trace["result"] == zlib.crc32(b"abc") & 0xFFFFFFFF
    assert trace["hex"] == "0x352441C2"
    assert len(trace["steps"]) == 3
    assert len(trace["steps"][0]["bits"]) == 8
    rendered = format_crc32_result(trace)
    assert "CRC-32（UTF-8）校验" in rendered
    assert "zlib.crc32 交叉验证一致" in rendered


def test_crc32_utf8_matches_standard_check_value() -> None:
    """摘要：锁定 ISO-HDLC CRC-32 标准 check 值，避免多项式或反射配置漂移。"""
    assert crc32_utf8("123456789")["hex"] == "0xCBF43926"


def test_crc32_utf8_rejects_input_over_64_bytes_without_truncation() -> None:
    with pytest.raises(ValueError, match="64 UTF-8 bytes"):
        crc32_utf8("a" * 65)


def test_euclidean_gcd_returns_remainder_sequence() -> None:
    trace = euclidean_gcd(48, 18)

    assert trace["algorithm"] == "euclidean_gcd"
    assert trace["result"] == 6
    assert [(item["a"], item["b"], item["remainder"]) for item in trace["steps"]] == [
        (48, 18, 12),
        (18, 12, 6),
        (12, 6, 0),
    ]
    rendered = format_gcd_result(trace)
    assert "48 mod 18 = 12" in rendered
    assert "gcd(48, 18) = 6" in rendered


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [(0, 7, 7), (0, 0, 0), (-48, 18, 6), (48, -18, 6)],
)
def test_euclidean_gcd_boundary_semantics(left: int, right: int, expected: int) -> None:
    assert euclidean_gcd(left, right)["result"] == expected


def test_quicksort_returns_expected_partition_snapshots() -> None:
    trace = quicksort([5, 2, 9, 1])

    assert trace["algorithm"] == "quicksort"
    assert trace["result"] == [1, 2, 5, 9]
    assert [item["snapshot"] for item in trace["partitions"]] == [
        [1, 2, 9, 5],
        [1, 2, 5, 9],
    ]
    rendered = format_quicksort_result(trace)
    assert "第 1 轮 pivot=1" in rendered
    assert "[1, 2, 5, 9]" in rendered
