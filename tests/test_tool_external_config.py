from __future__ import annotations

from pathlib import Path

import pytest

from offline_companion.shell.tool_registry.registry import ToolRegistry


def test_external_config_parses_disabled_default(tmp_path: Path) -> None:
    config_path = tmp_path / "tools_external.yaml"
    config_path.write_text(
        """
tools:
  - tool_id: web_search
    display_name: Web Search
    description: Search the web
    scope: network_egress
    permission: ask
    endpoint: http://localhost:8080/tool/web_search
    params_schema: {type: object}
    return_schema: {type: object}
    version: 0.1.0
""".strip(),
        encoding="utf-8",
    )

    manifests = ToolRegistry().load_external(config_path)

    assert manifests[0].enabled is False


def test_external_config_rejects_non_mapping_item(tmp_path: Path) -> None:
    config_path = tmp_path / "tools_external.yaml"
    config_path.write_text(
        """
tools:
  - invalid
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(TypeError, match="must be a mapping"):
        ToolRegistry().load_external(config_path)


def test_external_config_requires_endpoint(tmp_path: Path) -> None:
    config_path = tmp_path / "tools_external.yaml"
    config_path.write_text(
        """
tools:
  - tool_id: web_search
    display_name: Web Search
    description: Search the web
    scope: network_egress
    permission: ask
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires non-empty tool_id and endpoint"):
        ToolRegistry().load_external(config_path)
