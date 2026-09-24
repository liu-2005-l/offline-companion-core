"""摘要：用共享 golden fixture 验证 B1 Python 参考解析器。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from offline_companion.core.streaming_card_parser import parse_partial_card, scan_card_structure

FIXTURE_PATH = Path("fixtures/streaming_cards/b1_partial_parse_golden.json")
PYTHON_PARSER_PATH = Path("src/offline_companion/core/streaming_card_parser.py")
JS_PARSER_PATH = Path(
    "src/offline_companion/shell/ui_host/desktop/static/streaming_card_parser.js"
)


def _entries() -> list[pytest.param]:
    """摘要：展开全部单例和链节点为参数化判例。"""
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    entries: list[pytest.param] = []
    for case in payload["cases"]:
        entries.append(pytest.param(case, id=case["id"]))
    for chain in payload["chains"]:
        for index, entry in enumerate(chain["entries"]):
            entries.append(pytest.param(entry, id=f"{chain['id']}[{index}]"))
    return entries


@pytest.mark.parametrize("entry", _entries())
def test_python_partial_parser_matches_shared_golden(entry: dict[str, object]) -> None:
    """摘要：Python 参考实现必须逐字段等于共享 golden。"""
    result = parse_partial_card(str(entry["buffer"]))
    scan = scan_card_structure(str(entry["buffer"]))

    assert {
        "value": result.value,
        "closed": result.closed,
        "complete": result.complete,
    } == entry["expected"]
    assert scan.l0_active is entry["l0_active"]


def test_python_partial_parser_discards_closed_paths_after_late_structure_failure() -> None:
    """摘要：后置多余闭合符必须让 value 与已扫描 closed 一并失败短路。"""
    buffer = '{"steps":[{"a":1}]}]'

    result = parse_partial_card(buffer)
    scan = scan_card_structure(buffer)

    assert result.value is None
    assert result.closed == []
    assert result.complete is False
    assert scan.valid is False
    assert scan.closed == []


def test_python_parser_does_not_restore_trial_json_parse() -> None:
    """摘要：Python 解析器不得重新引入 ``json.loads`` 参与完整性判定。"""
    source = PYTHON_PARSER_PATH.read_text(encoding="utf-8")

    assert "json.loads(" not in source


def test_javascript_parser_does_not_restore_trial_json_parse() -> None:
    """摘要：JavaScript 解析器不得重新引入 ``JSON.parse`` 参与完整性判定。"""
    source = JS_PARSER_PATH.read_text(encoding="utf-8")

    assert "JSON.parse(" not in source
