"""摘要：提供流式卡片 JSON 的无状态增量解析参考实现。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PartialParse:
    """摘要：描述一个流式卡片缓冲区的当前可解析状态。

    参数：
        value: 修复未完成前缀后得到的对象，失败时为 ``None``。
        closed: 原文中已真实闭合的直接卡片路径。
        complete: 原文是否为词法和结构均完整的 JSON 对象。
    """

    value: dict[str, Any] | None
    closed: list[str]
    complete: bool


@dataclass(frozen=True)
class StructuralScan:
    """摘要：记录原始缓冲区的结构扫描结果。

    参数：
        closed: 原文中已真实闭合的直接卡片路径。
        open_stack: 尚未闭合的容器类型序列。
        l0_active: 是否已识别顶层 ``steps`` 数组入口。
        valid: 是否未发生括号类型不匹配或栈下溢。
        lexical_complete: 是否没有未闭合字符串或转义。
    """

    closed: list[str]
    open_stack: list[str]
    l0_active: bool
    valid: bool
    lexical_complete: bool


@dataclass
class _Frame:
    kind: str
    path: str
    next_index: int = 0
    pending_key: str | None = None


class _ParseFailure(ValueError):
    pass


class _PartialJsonParser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.length = len(source)
        self.index = 0

    def parse(self) -> dict[str, Any]:
        self._skip_ws()
        if self._peek() != "{":
            raise _ParseFailure
        value = self._parse_object()
        self._skip_ws()
        if self.index != self.length:
            raise _ParseFailure
        return value

    def _parse_object(self) -> dict[str, Any]:
        self._consume("{")
        value: dict[str, Any] = {}
        self._skip_ws()
        if self._at_end():
            return value
        if self._peek() == "}":
            self.index += 1
            return value

        while True:
            self._skip_ws()
            if self._at_end():
                return value
            if self._peek() != '"':
                raise _ParseFailure
            key, key_complete = self._parse_string()
            if not key_complete:
                return value
            self._skip_ws()
            if self._at_end():
                return value
            if self._peek() != ":":
                raise _ParseFailure
            self.index += 1
            self._skip_ws()
            if self._at_end():
                value[key] = None
                return value
            value[key] = self._parse_value()
            self._skip_ws()
            if self._at_end():
                return value
            marker = self._peek()
            if marker == "}":
                self.index += 1
                return value
            if marker != ",":
                raise _ParseFailure
            self.index += 1
            self._skip_ws()
            if self._at_end():
                return value

    def _parse_array(self) -> list[Any]:
        self._consume("[")
        value: list[Any] = []
        self._skip_ws()
        if self._at_end():
            return value
        if self._peek() == "]":
            self.index += 1
            return value

        while True:
            self._skip_ws()
            if self._at_end():
                return value
            value.append(self._parse_value())
            self._skip_ws()
            if self._at_end():
                return value
            marker = self._peek()
            if marker == "]":
                self.index += 1
                return value
            if marker != ",":
                raise _ParseFailure
            self.index += 1
            self._skip_ws()
            if self._at_end():
                return value

    def _parse_value(self) -> Any:
        marker = self._peek()
        if marker == "{":
            return self._parse_object()
        if marker == "[":
            return self._parse_array()
        if marker == '"':
            value, _complete = self._parse_string()
            return value
        if marker in "tfn":
            return self._parse_literal()
        if marker == "-" or marker.isdigit():
            return self._parse_number()
        raise _ParseFailure

    def _parse_string(self) -> tuple[str, bool]:
        self._consume('"')
        result: list[str] = []
        escapes = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        while not self._at_end():
            char = self.source[self.index]
            self.index += 1
            if char == '"':
                return "".join(result), True
            if char != "\\":
                if ord(char) < 0x20:
                    raise _ParseFailure
                result.append(char)
                continue
            if self._at_end():
                return "".join(result), False
            escaped = self.source[self.index]
            if escaped == "u":
                digits = self.source[self.index + 1 : self.index + 5]
                if len(digits) < 4:
                    self.index = self.length
                    return "".join(result), False
                if not re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    raise _ParseFailure
                result.append(chr(int(digits, 16)))
                self.index += 5
                continue
            replacement = escapes.get(escaped)
            if replacement is None:
                raise _ParseFailure
            result.append(replacement)
            self.index += 1
        return "".join(result), False

    def _parse_literal(self) -> bool | None:
        start = self.index
        while not self._at_end() and self._peek().isalpha():
            self.index += 1
        token = self.source[start : self.index]
        values: dict[str, bool | None] = {"true": True, "false": False, "null": None}
        if token in values:
            return values[token]
        if any(literal.startswith(token) for literal in values):
            return None
        raise _ParseFailure

    def _parse_number(self) -> int | float | None:
        start = self.index
        while not self._at_end() and self._peek() not in " \t\r\n,]}":
            self.index += 1
        token = self.source[start : self.index]
        if re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?", token):
            return float(token) if "." in token or "e" in token.lower() else int(token)
        if re.fullmatch(r"-?(?:(?:0|[1-9]\d*)?(?:\.)?|(?:0|[1-9]\d*)(?:\.\d+)?[eE][+-]?)", token):
            return None
        raise _ParseFailure

    def _skip_ws(self) -> None:
        while not self._at_end() and self.source[self.index] in " \t\r\n":
            self.index += 1

    def _consume(self, expected: str) -> None:
        if self._peek() != expected:
            raise _ParseFailure
        self.index += 1

    def _peek(self) -> str:
        return self.source[self.index] if not self._at_end() else ""

    def _at_end(self) -> bool:
        return self.index >= self.length


def parse_partial_card(buffer: str) -> PartialParse:
    """摘要：解析一个流式卡片 JSON 前缀并返回可渲染状态。

    参数：
        buffer: 从当前生成 attempt 起累计的原始文本。

    返回值：
        修复后的对象、原文闭合卡片路径与原文完整性。
    """
    scan = scan_card_structure(buffer)
    if not scan.valid:
        return PartialParse(value=None, closed=[], complete=False)
    try:
        value = _PartialJsonParser(buffer).parse()
    except _ParseFailure:
        return PartialParse(value=None, closed=[], complete=False)

    complete = scan.lexical_complete and not scan.open_stack
    return PartialParse(value=value, closed=scan.closed, complete=complete)


def scan_card_structure(buffer: str) -> StructuralScan:
    """摘要：只依据原文扫描结构闭合路径和 L0 状态。

    参数：
        buffer: 从当前生成 attempt 起累计的原始文本。

    返回值：
        原文闭合路径、开放容器栈、L0 状态与结构有效性。
    """
    source = str(buffer)
    frames: list[_Frame] = []
    closed: list[str] = []
    index = 0
    in_string = False
    escape = False
    string_start = 0
    l0_active = False
    valid = True

    while index < len(source):
        char = source[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
                next_index = index + 1
                while next_index < len(source) and source[next_index] in " \t\r\n":
                    next_index += 1
                if (
                    frames
                    and frames[-1].kind == "object"
                    and next_index < len(source)
                    and source[next_index] == ":"
                ):
                    try:
                        parser = _PartialJsonParser(source[string_start : index + 1])
                        key, key_complete = parser._parse_string()
                        if not key_complete or not parser._at_end():
                            raise _ParseFailure
                        frames[-1].pending_key = key
                    except _ParseFailure:
                        valid = False
                        break
            index += 1
            continue

        if char == '"':
            in_string = True
            string_start = index
            index += 1
            continue
        if char in "{[":
            path = _child_path(frames)
            if char == "[" and path == "steps" and len(frames) == 1:
                l0_active = True
            frames.append(_Frame(kind="object" if char == "{" else "array", path=path))
        elif char in "}]":
            expected = "object" if char == "}" else "array"
            if not frames or frames[-1].kind != expected:
                valid = False
                break
            frame = frames.pop()
            if frame.kind == "object" and re.fullmatch(r"steps\[\d+\]", frame.path):
                closed.append(frame.path)
        elif char == "," and frames:
            frame = frames[-1]
            if frame.kind == "array":
                frame.next_index += 1
            else:
                frame.pending_key = None
        index += 1

    lexical_complete = not in_string and not escape
    return StructuralScan(
        closed=closed if valid else [],
        open_stack=[frame.kind for frame in frames] if valid else [],
        l0_active=l0_active if valid else False,
        valid=valid,
        lexical_complete=lexical_complete,
    )


def _child_path(frames: list[_Frame]) -> str:
    if not frames:
        return ""
    parent = frames[-1]
    if parent.kind == "array":
        return f"{parent.path}[{parent.next_index}]"
    key = parent.pending_key
    parent.pending_key = None
    if key is None:
        return parent.path
    return f"{parent.path}.{key}" if parent.path else key
