"""声明式 PluginLoader 测试。"""

import asyncio
from types import SimpleNamespace

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.lifecycle import PluginLoader, PluginsConfig


def run(coro):
    return asyncio.run(coro)


def test_loader_loads_in_dependency_order_unloads_in_reverse(monkeypatch) -> None:
    calls: list[str] = []

    def make_factory(plugin_id):
        def factory(context):
            calls.append(plugin_id)
            context.effect.add_disposer(lambda: calls.append(f"dispose-{plugin_id}"))
            return {"id": plugin_id, "dependency": context.services}

        return factory

    modules = {
        "plugins.a": SimpleNamespace(create_plugin=make_factory("a")),
        "plugins.b": SimpleNamespace(create_plugin=make_factory("b")),
        "plugins.c": SimpleNamespace(create_plugin=make_factory("c")),
    }
    monkeypatch.setattr("offline_companion.core.lifecycle.loader.importlib.import_module", modules.__getitem__)
    config = PluginsConfig.from_mapping(
        {
            "schema_version": 1,
            "plugins": [
                {"id": "a", "module": "plugins.a", "requires": ["b"]},
                {"id": "b", "module": "plugins.b", "requires": ["c"]},
                {"id": "c", "module": "plugins.c"},
            ],
        }
    )
    loader = PluginLoader(config, event_stream=EventStream("plugins", build_default_registry()))

    fibers = run(loader.load_all())
    run(loader.unload_all())

    assert calls == ["c", "b", "a", "dispose-a", "dispose-b", "dispose-c"]
    assert all(fiber.state.value == "disposed" for fiber in fibers.values())


def test_loader_dump_config_reports_pending_and_active(monkeypatch) -> None:
    monkeypatch.setattr(
        "offline_companion.core.lifecycle.loader.importlib.import_module",
        lambda _name: SimpleNamespace(create_plugin=lambda _context: "service"),
    )
    loader = PluginLoader(
        PluginsConfig.from_mapping(
            {
                "schema_version": 1,
                "plugins": [
                    {"id": "active", "module": "plugins.active"},
                    {"id": "disabled", "module": "plugins.disabled", "enabled": False},
                ],
            }
        )
    )

    run(loader.load_all())
    dump = loader.dump_config()

    assert dump["config"]["schema_version"] == 1
    assert {item["id"]: item["state"] for item in dump["plugins"]} == {
        "active": "active",
        "disabled": "pending",
    }
