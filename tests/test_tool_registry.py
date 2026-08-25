from __future__ import annotations

from pathlib import Path

import pytest

from offline_companion.core.tools.datetime_tool import datetime_now
from offline_companion.shared.types import PrivacyMode, ToolManifest
from offline_companion.shell.tool_registry.registry import ToolRegistry


def _builtin_manifest(*, permission: str = "allow", scope: str = "datetime") -> ToolManifest:
    return ToolManifest(
        tool_id="datetime_now",
        display_name="Datetime Now",
        description="Return current UTC time",
        tool_type="builtin",
        permission=permission,  # type: ignore[arg-type]
        scope=scope,
        params_schema={"type": "object"},
        return_schema={"type": "object"},
        handler_module="offline_companion.core.tools.datetime_tool",
        handler_function="datetime_now",
        external_config=None,
        version="0.1.0",
        algorithm_names=("booth",),
        trigger_keywords=("最大公约数",),
    )


def test_registry_registers_builtin_and_lists_available() -> None:
    registry = ToolRegistry()
    registry.register_builtin(_builtin_manifest(), datetime_now)

    manifests = registry.list_available()

    assert len(manifests) == 1
    assert manifests[0].tool_id == "datetime_now"
    assert registry.get_builtin_handler("datetime_now") is datetime_now


def test_registry_exposes_available_algorithm_and_trigger_unions() -> None:
    """摘要：Tool 注册表是算法专名与裸意图词典的唯一来源。"""
    registry = ToolRegistry()
    registry.register_builtin(_builtin_manifest(), datetime_now)

    assert registry.algorithm_names() == frozenset({"booth"})
    assert registry.trigger_keywords() == frozenset({"最大公约数"})


def test_resolve_permission_respects_local_only_for_network_scope() -> None:
    registry = ToolRegistry()
    registry.register_builtin(_builtin_manifest(permission="ask", scope="network_egress"), datetime_now)

    permission = registry.resolve_permission("datetime_now", privacy_mode=PrivacyMode.LOCAL_ONLY)

    assert permission == "deny"


def test_load_external_defaults_to_disabled(tmp_path: Path) -> None:
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
    registry = ToolRegistry()

    manifests = registry.load_external(config_path)

    assert manifests[0].tool_type == "external"
    assert manifests[0].enabled is False
    assert registry.resolve_permission("web_search", privacy_mode=PrivacyMode.AUTO_ROUTE_CLOUD) == "deny"
    assert registry.algorithm_names() == frozenset()


def test_enabled_external_metadata_participates_in_unions(tmp_path: Path) -> None:
    """摘要：启用的 external Tool 元数据参与同源词典，禁用状态不泄漏。"""
    config_path = tmp_path / "tools_external.yaml"
    config_path.write_text(
        """
tools:
  - tool_id: crc_tool
    display_name: CRC Tool
    description: Compute CRC
    scope: local_computation
    permission: ask
    endpoint: http://localhost:8080/tool/crc
    enabled: true
    algorithm_names: [crc]
    trigger_keywords: [校验值]
""".strip(),
        encoding="utf-8",
    )
    registry = ToolRegistry()

    registry.load_external(config_path)

    assert registry.algorithm_names() == frozenset({"crc"})
    assert registry.trigger_keywords() == frozenset({"校验值"})


def test_load_external_rejects_allow_permission(tmp_path: Path) -> None:
    config_path = tmp_path / "tools_external.yaml"
    config_path.write_text(
        """
tools:
  - tool_id: web_search
    display_name: Web Search
    description: Search the web
    scope: network_egress
    permission: allow
    endpoint: http://localhost:8080/tool/web_search
""".strip(),
        encoding="utf-8",
    )
    registry = ToolRegistry()

    with pytest.raises(ValueError, match="cannot be 'allow'"):
        registry.load_external(config_path)
