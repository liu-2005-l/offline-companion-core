"""插件声明式配置 API 测试。"""

from tests.test_desktop_http import _runtime

from offline_companion.core.lifecycle import PluginLoader, PluginsConfig
from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app


def test_plugin_config_endpoint_dumps_loader_state(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.plugin_loader = PluginLoader(
        PluginsConfig.from_mapping(
            {"schema_version": 1, "plugins": [{"id": "demo", "module": "plugins.demo"}]}
        )
    )
    client = create_desktop_app(runtime).test_client()

    response = client.get("/api/plugins/config")

    assert response.status_code == 200
    assert response.get_json()["config"]["schema_version"] == 1
