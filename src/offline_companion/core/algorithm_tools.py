"""摘要：提供无需 LLM 推理的确定性算法工具。"""

from __future__ import annotations

from typing import Any


def booth_multiply(multiplicand: int, multiplier: int) -> dict[str, Any]:
    """摘要：使用 Booth 算法计算两个整数并返回完整中间态。

    参数：
        multiplicand: 被乘数。
        multiplier: 乘数。

    返回值：
        包含最终结果、重编码表达式和每轮寄存器变化的字典。

    Raises:
        TypeError: 参数不是整数或是布尔值。
        ValueError: 参数超出当前工具支持的安全范围。
    """
    if isinstance(multiplicand, bool) or isinstance(multiplier, bool):
        raise TypeError("Booth operands must be integers")
    if not isinstance(multiplicand, int) or not isinstance(multiplier, int):
        raise TypeError("Booth operands must be integers")
    if abs(multiplicand).bit_length() > 62 or abs(multiplier).bit_length() > 62:
        raise ValueError("Booth operands exceed the supported 62-bit range")

    width = max(abs(multiplicand).bit_length(), abs(multiplier).bit_length(), 1) + 1
    mask = (1 << width) - 1
    accumulator = 0
    multiplicand_register = _to_twos_complement(multiplicand, width)
    multiplier_register = _to_twos_complement(multiplier, width)
    previous_multiplier_bit = 0
    rounds: list[dict[str, Any]] = []

    for round_index in range(width):
        pair = f"{multiplier_register & 1}{previous_multiplier_bit}"
        before = _signed(accumulator, width)
        operation = "保持 A"
        if pair == "10":
            accumulator = (accumulator - multiplicand_register) & mask
            operation = f"A = A - M ({before} - {multiplicand})"
        elif pair == "01":
            accumulator = (accumulator + multiplicand_register) & mask
            operation = f"A = A + M ({before} + {multiplicand})"

        after_operation = _signed(accumulator, width)
        combined = (accumulator << (width + 1)) | (multiplier_register << 1) | previous_multiplier_bit
        if accumulator & (1 << (width - 1)):
            combined = (combined | ~((1 << (2 * width + 1)) - 1)) >> 1
        else:
            combined >>= 1
        accumulator = (combined >> (width + 1)) & mask
        multiplier_register = (combined >> 1) & mask
        previous_multiplier_bit = combined & 1
        rounds.append(
            {
                "round": round_index + 1,
                "pair": pair,
                "operation": operation,
                "accumulator_before": before,
                "accumulator_after_operation": after_operation,
                "accumulator_after_shift": _signed(accumulator, width),
                "multiplier_after_shift": _signed(multiplier_register, width),
                "previous_multiplier_bit": previous_multiplier_bit,
            }
        )

    result_register = (accumulator << width) | multiplier_register
    result = _signed(result_register, 2 * width)
    if result != multiplicand * multiplier:
        raise ArithmeticError("Booth register trace produced an inconsistent result")
    recoding_terms = _booth_terms(multiplier)
    return {
        "algorithm": "booth",
        "multiplicand": multiplicand,
        "multiplier": multiplier,
        "bit_width": width,
        "recoding": _booth_recoding(multiplier),
        "partial_products": [coefficient * power * multiplicand for coefficient, power in recoding_terms],
        "rounds": rounds,
        "result": result,
    }


def format_booth_result(trace: dict[str, Any]) -> str:
    """摘要：将 Booth 工具结果格式化为可交给 LLM 转述的本地文本。"""
    lines = [
        f"Booth 算法：{trace['multiplicand']} x {trace['multiplier']} = {trace['result']}。",
        f"乘数重编码：{trace['recoding']}。",
        f"部分积：{_format_sum(trace['partial_products'])} = {trace['result']}。",
        "逐轮中间态：",
    ]
    for item in trace["rounds"]:
        lines.append(
            f"第{item['round']}轮，Q0Q-1={item['pair']}，{item['operation']}；"
            f"右移后 A={item['accumulator_after_shift']}，Q={item['multiplier_after_shift']}。"
        )
    return "\n".join(lines)


def _to_twos_complement(value: int, width: int) -> int:
    return value & ((1 << width) - 1)


def _signed(value: int, width: int) -> int:
    sign_bit = 1 << (width - 1)
    return value - (1 << width) if value & sign_bit else value


def _booth_recoding(value: int) -> str:
    """摘要：生成连续 1 区间的 Booth 有符号幂次表达式。"""
    if value == 0:
        return "0 = 0"
    terms = _booth_terms(value)
    rendered = " ".join(
        ("+" if coefficient > 0 else "-") + str(power)
        for coefficient, power in terms
    ).strip()
    return f"{value} = -({rendered})" if value < 0 else f"{value} = {rendered}"


def _booth_terms(value: int) -> list[tuple[int, int]]:
    """摘要：返回从高位到低位排列的 Booth 有符号幂次项。"""
    if value == 0:
        return []
    sign = -1 if value < 0 else 1
    magnitude = abs(value)
    terms: list[tuple[int, int]] = []
    previous = 0
    for index in range(magnitude.bit_length() + 1):
        current = (magnitude >> index) & 1
        if previous == 0 and current == 1:
            terms.append((-sign, 1 << index))
        elif previous == 1 and current == 0:
            terms.append((sign, 1 << index))
        previous = current
    return list(reversed(terms))


def _format_sum(values: list[int]) -> str:
    """摘要：将有符号部分积格式化为可读的加减表达式。"""
    if not values:
        return "0"
    first, *rest = values
    rendered = str(first)
    for value in rest:
        rendered += f" + {value}" if value >= 0 else f" - {abs(value)}"
    return rendered
