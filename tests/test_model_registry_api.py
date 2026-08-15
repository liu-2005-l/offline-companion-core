"""模型注册表与本地模型目录 API 测试。"""

from tests.test_desktop_http import _runtime

from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
from offline_companion.shell.ui_host.model_registry import BUILTIN_MODELS, ModelDirectory


def test_model_registry_endpoint_exposes_builtin_metadata(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()

    payload = client.get("/api/models/registry").get_json()

    assert payload["total"] == len(BUILTIN_MODELS)
    assert payload["items"][0]["recommended"] is True
    assert payload["items"][0]["downloaded"] is False
    assert payload["items"][0]["sha256"]
    assert len(payload["items"][0]["download_urls"]) == 2


def test_local_models_endpoint_lists_downloaded_models(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    directory = ModelDirectory(tmp_path)
    directory.ensure_dir()
    directory.model_path("demo-model").write_bytes(b"gguf")
    directory.model_path("empty-model").touch()
    client = create_desktop_app(runtime).test_client()

    payload = client.get("/api/models/local").get_json()

    assert payload["total"] == 1
    assert payload["items"][0]["model_id"] == "demo-model"
    assert payload["items"][0]["size_bytes"] == 4
