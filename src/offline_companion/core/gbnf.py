"""gbnf：为扁平 builtin Tool 选择生成实验用 GBNF 文法。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def tool_schema_to_gbnf(tools: Sequence[Mapping[str, Any]]) -> str:
    """摘要：从工具描述生成单工具或 ``none`` 输出文法。

    参数：
        tools: 包含 ``tool_id`` 与扁平 ``params_schema`` 的工具描述。

    返回值：
        可传给 llama-server 的 GBNF 文本。
    """
    tool_names = [str(tool.get("tool_id") or "").strip() for tool in tools]
    tool_names = [name for name in tool_names if name]
    if not tool_names:
        raise ValueError("at least one tool is required")
    alternatives = " | ".join(_quoted_json(name) for name in [*tool_names, "none"])
    rules = [
        'root ::= "{" ws "\\"name\\":" name "," ws "\\"parameters\\":" parameters "}"',
        f"name ::= {alternatives}",
        'parameters ::= "{}" | object',
        'object ::= "{" ws members ws "}"',
        'members ::= member (ws "," ws member)*',
        'member ::= string ws ":" ws value',
        'value ::= string | number | boolean',
        'string ::= "\\\"" chars "\\\""',
        'chars ::= [^"\\\\] [^"\\\\]*',
        'number ::= [0-9] [0-9.-]*',
        'boolean ::= "true" | "false"',
        'ws ::= [ \t\n]*',
    ]
    for tool in tools:
        tool_id = str(tool.get("tool_id") or "").strip()
        schema = tool.get("params_schema") or {}
        if not isinstance(schema, Mapping):
            raise TypeError(f"invalid params_schema for {tool_id}")
        required = schema.get("required") or []
        properties = schema.get("properties") or {}
        if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
            raise TypeError(f"invalid required fields for {tool_id}")
        if not isinstance(properties, Mapping):
            raise TypeError(f"invalid properties for {tool_id}")
        for field in required:
            if str(field) not in properties:
                raise ValueError(f"required field {field!r} missing from {tool_id}")
    return "\n".join(rules)


def _quoted_json(value: str) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    return '"' + encoded[1:-1].replace('"', '\\"') + '"'
