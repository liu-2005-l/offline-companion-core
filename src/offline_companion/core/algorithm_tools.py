"""摘要：提供无需 LLM 推理的确定性算法工具。"""

from __future__ import annotations

import zlib
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


def crc32_utf8(text: str) -> dict[str, Any]:
    """摘要：按 CRC-32 标准多项式对 UTF-8 字节执行确定性校验并返回按位轨迹。

    参数：
        text: 待校验文本，固定使用 UTF-8 编码。

    返回值：
        包含字节输入、按位迭代轨迹、十六进制校验值和 zlib 交叉验证结果的字典。

    Raises:
        TypeError: 输入不是字符串。
        ArithmeticError: 自实现结果与 zlib.crc32 不一致。
    """
    if not isinstance(text, str):
        raise TypeError("CRC-32 input must be a string")
    data = text.encode("utf-8")
    crc = 0xFFFFFFFF
    steps: list[dict[str, Any]] = []
    for byte_index, byte in enumerate(data):
        crc ^= byte
        bit_steps: list[dict[str, Any]] = []
        for bit_index in range(8):
            before = crc
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
                operation = "右移后异或反射多项式 0xEDB88320"
            else:
                crc >>= 1
                operation = "右移"
            crc &= 0xFFFFFFFF
            bit_steps.append(
                {
                    "bit": bit_index,
                    "before": f"0x{before:08X}",
                    "after": f"0x{crc:08X}",
                    "operation": operation,
                }
            )
        steps.append(
            {
                "byte_index": byte_index,
                "byte": byte,
                "char": chr(byte) if 32 <= byte <= 126 else "",
                "after_xor_and_bits": f"0x{crc:08X}",
                "bits": bit_steps,
            }
        )
    result = crc ^ 0xFFFFFFFF
    expected = zlib.crc32(data) & 0xFFFFFFFF
    if result != expected:
        raise ArithmeticError("CRC-32 implementation diverged from zlib.crc32")
    return {
        "algorithm": "crc32",
        "input": text,
        "encoding": "utf-8",
        "bytes": list(data),
        "polynomial": "0xEDB88320",
        "steps": steps,
        "result": result,
        "hex": f"0x{result:08X}",
        "zlib_crc32": expected,
    }


def format_crc32_result(trace: dict[str, Any]) -> str:
    """摘要：将 CRC-32 工具结果格式化为可转述文本。"""
    lines = [
        f"CRC-32（UTF-8）校验：{trace['input']!r} -> {trace['hex']}。",
        f"输入字节：{trace['bytes']}；多项式：{trace['polynomial']}。",
        "按位迭代摘要：",
    ]
    for item in trace["steps"]:
        lines.append(
            f"第 {item['byte_index'] + 1} 个字节 {item['byte']} 处理后 CRC={item['after_xor_and_bits']}。"
        )
    lines.append(f"zlib.crc32 交叉验证一致：0x{trace['zlib_crc32']:08X}。")
    return "\n".join(lines)


def euclidean_gcd(left: int, right: int) -> dict[str, Any]:
    """摘要：使用欧几里得算法计算最大公约数并返回余数序列。

    参数：
        left: 第一个整数。
        right: 第二个整数。

    返回值：
        包含原始输入、余数步骤和最大公约数的字典。

    Raises:
        TypeError: 参数不是整数或是布尔值。
        ValueError: 两个参数不能同时为 0。
    """
    if isinstance(left, bool) or isinstance(right, bool):
        raise TypeError("GCD operands must be integers")
    if not isinstance(left, int) or not isinstance(right, int):
        raise TypeError("GCD operands must be integers")
    if left == 0 and right == 0:
        raise ValueError("GCD is undefined for 0 and 0")
    a = abs(left)
    b = abs(right)
    steps: list[dict[str, int]] = []
    while b:
        quotient, remainder = divmod(a, b)
        steps.append({"a": a, "b": b, "quotient": quotient, "remainder": remainder})
        a, b = b, remainder
    return {
        "algorithm": "euclidean_gcd",
        "left": left,
        "right": right,
        "steps": steps,
        "result": a,
    }


def format_gcd_result(trace: dict[str, Any]) -> str:
    """摘要：将欧几里得算法结果格式化为可转述文本。"""
    lines = [f"欧几里得算法：gcd({trace['left']}, {trace['right']}) = {trace['result']}。"]
    for item in trace["steps"]:
        lines.append(
            f"{item['a']} mod {item['b']} = {item['remainder']}（商 {item['quotient']}）。"
        )
    return "\n".join(lines)


def quicksort(values: list[int]) -> dict[str, Any]:
    """摘要：使用确定性快速排序对整数列表排序并返回分区快照。

    参数：
        values: 待排序整数列表。

    返回值：
        包含原始列表、分区快照和排序结果的字典。

    Raises:
        TypeError: 输入不是整数列表或包含布尔值。
    """
    if not isinstance(values, list):
        raise TypeError("quicksort input must be a list")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise TypeError("quicksort values must be integers")
    array = list(values)
    snapshots: list[dict[str, Any]] = []

    def partition(low: int, high: int) -> int:
        pivot = array[high]
        pivot_index = low
        for scan_index in range(low, high):
            if array[scan_index] <= pivot:
                array[pivot_index], array[scan_index] = array[scan_index], array[pivot_index]
                pivot_index += 1
        array[pivot_index], array[high] = array[high], array[pivot_index]
        snapshots.append(
            {
                "low": low,
                "high": high,
                "pivot": pivot,
                "pivot_index": pivot_index,
                "snapshot": list(array),
            }
        )
        return pivot_index

    def sort(low: int, high: int) -> None:
        if low >= high:
            return
        pivot_index = partition(low, high)
        sort(low, pivot_index - 1)
        sort(pivot_index + 1, high)

    sort(0, len(array) - 1)
    return {
        "algorithm": "quicksort",
        "input": list(values),
        "partitions": snapshots,
        "result": array,
    }


def format_quicksort_result(trace: dict[str, Any]) -> str:
    """摘要：将快速排序结果格式化为可转述文本。"""
    lines = [f"快速排序：{trace['input']} -> {trace['result']}。", "分区快照："]
    for index, item in enumerate(trace["partitions"], start=1):
        lines.append(
            f"第 {index} 轮 pivot={item['pivot']}，区间 [{item['low']}, {item['high']}]，"
            f"快照 {item['snapshot']}。"
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
