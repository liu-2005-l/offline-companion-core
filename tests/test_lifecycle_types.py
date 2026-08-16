"""插件生命周期类型测试。"""

from offline_companion.core.lifecycle import LifecycleState, PluginDefinition


def test_lifecycle_state_values_are_stable() -> None:
    assert [state.value for state in LifecycleState] == [
        "pending",
        "loading",
        "active",
        "failed",
        "unloading",
        "disposed",
    ]


def test_plugin_definition_defaults() -> None:
    definition = PluginDefinition(id="demo", factory=lambda _context: None)

    assert definition.config_schema is None
    assert definition.requires == []
    assert definition.optional_requires == []
    assert definition.version == "1.0.0"
