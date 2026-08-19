from __future__ import annotations

from tests.test_desktop_http import _runtime

from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app


def test_settings_api_returns_nested_snapshot_and_module_patch(tmp_path) -> None:
    client = create_desktop_app(_runtime(tmp_path)).test_client()

    full = client.get("/api/settings")
    assert full.status_code == 200
    assert full.get_json()["data"]["schema_version"] == 2
    assert "appearance" in full.get_json()["data"]

    patched = client.patch("/api/settings/appearance", json={"corner_radius": 8})
    assert patched.status_code == 200
    assert patched.get_json()["data"]["corner_radius"] == 8

    module = client.get("/api/settings/appearance")
    assert module.get_json()["data"]["theme"] == "light"


def test_settings_api_rejects_unknown_module(tmp_path) -> None:
    client = create_desktop_app(_runtime(tmp_path)).test_client()

    assert client.get("/api/settings/unknown").status_code == 404
    assert client.patch("/api/settings/unknown", json={"x": 1}).status_code == 404
