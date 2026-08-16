"""声明式插件配置与依赖图测试。"""

import pytest

from offline_companion.core.lifecycle import (
    CircularDependencyError,
    MissingDependencyError,
    PluginConfigEntry,
    PluginConfigError,
    PluginsConfig,
    topological_sort,
)


def entry(plugin_id: str, requires: list[str] | None = None, enabled: bool = True) -> PluginConfigEntry:
    return PluginConfigEntry(plugin_id, f"plugins.{plugin_id}", enabled, tuple(requires or []))


def test_config_rejects_unknown_fields_and_duplicate_ids() -> None:
    with pytest.raises(PluginConfigError, match="unknown plugin fields"):
        PluginConfigEntry.from_mapping({"id": "demo", "module": "demo", "unexpected": True})
    with pytest.raises(PluginConfigError, match="plugin ids must be unique"):
        PluginsConfig.from_mapping(
            {"schema_version": 1, "plugins": [{"id": "a", "module": "a"}, {"id": "a", "module": "b"}]}
        )


def test_topological_sort_preserves_dependency_order() -> None:
    result = topological_sort([entry("a", ["b"]), entry("b", ["c"]), entry("c")])

    assert [item.id for item in result] == ["c", "b", "a"]


def test_topological_sort_rejects_missing_and_circular_dependencies() -> None:
    with pytest.raises(MissingDependencyError):
        topological_sort([entry("a", ["missing"])])
    with pytest.raises(CircularDependencyError):
        topological_sort([entry("a", ["b"]), entry("b", ["a"])])


def test_topological_sort_ignores_disabled_plugin() -> None:
    result = topological_sort([entry("disabled", enabled=False), entry("active")])

    assert [item.id for item in result] == ["active"]
