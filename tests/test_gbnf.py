import pytest

from offline_companion.core.gbnf import tool_schema_to_gbnf


def test_tool_schema_to_gbnf_includes_tools_and_none() -> None:
    grammar = tool_schema_to_gbnf(
        [
            {
                "tool_id": "calculator",
                "params_schema": {
                    "type": "object",
                    "required": ["left"],
                    "properties": {"left": {"type": "integer"}},
                },
            }
        ]
    )

    assert '"calculator"' in grammar
    assert '"none"' in grammar
    assert "parameters" in grammar


def test_tool_schema_to_gbnf_rejects_missing_required_property() -> None:
    with pytest.raises(ValueError, match="missing"):
        tool_schema_to_gbnf(
            [{"tool_id": "calculator", "params_schema": {"required": ["left"], "properties": {}}}]
        )
