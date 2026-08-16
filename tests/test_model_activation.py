"""下载完成后的本地模型自动激活测试。"""

import json
import time
from pathlib import Path
from types import SimpleNamespace

from tests.test_desktop_http import _runtime

import offline_companion.shell.ui_host.desktop.http_host as desktop_http
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.shared.types import ModelDescriptor
from offline_companion.shell.auto_router import AutoRouter
from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
from offline_companion.shell.ui_host.model_downloader import DownloadProgress, DownloadState
from offline_companion.shell.ui_host.model_registry import BUILTIN_MODELS


class _Downloader:
    def __init__(self, path: Path, *, fail: bool = False) -> None:
        self.path = path
        self.fail = fail
        self.progress = None

    def get_progress(self, model_id: str):
        return self.progress if self.progress and self.progress.model_id == model_id else None

    def download(self, model_id: str) -> Path:
        if self.fail:
            raise RuntimeError("download failed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"gguf")
        self.progress = DownloadProgress(
            model_id, DownloadState.COMPLETED, 4, 4, 1.0, None, "test", 1, 0
        )
        return self.path

    def cancel(self, _model_id: str) -> None:
        return None


class _StoppableBackend(EchoBackend):
    def __init__(self) -> None:
        super().__init__("old")
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _wait_for_completion(client, model_id: str) -> dict:
    for _ in range(100):
        payload = client.get("/api/models/download/status").get_json()
        if payload["items"] and payload["items"][0]["state"] in {"completed", "failed"}:
            return payload["items"][0]
        time.sleep(0.01)
    raise AssertionError(f"download did not finish: {model_id}")


def test_download_completion_activates_backend_and_auto_router(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    old_backend = _StoppableBackend()
    runtime.orchestrator.backend = old_backend
    router = AutoRouter()
    runtime.auto_turn_orchestrator = SimpleNamespace(auto_bridge=SimpleNamespace(auto_router=router))
    downloader = _Downloader(tmp_path / "models" / "downloaded.gguf")
    runtime.model_downloader = downloader
    model_id = BUILTIN_MODELS[0].model_id
    descriptor = ModelDescriptor(
        model_id=model_id,
        display_name="Downloaded Model",
        gguf_path=None,
        source="test",
        status="needs_config",
        backend="llama_cpp",
    )
    monkeypatch.setattr(desktop_http, "describe_model", lambda *args, **kwargs: descriptor)
    monkeypatch.setattr(
        desktop_http,
        "_load_local_model_backend",
        lambda _runtime, _model: EchoBackend(model_id),
    )
    client = create_desktop_app(runtime).test_client()

    assert client.post("/api/models/download", json={"model_id": model_id}).status_code == 202
    assert _wait_for_completion(client, model_id)["state"] == "completed"

    assert runtime.orchestrator.backend.label == model_id
    assert old_backend.stopped is True
    assert router.active_model_id == model_id
    assert router.active_model_path == str(downloader.path)
    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert settings["active_model_id"] == model_id


def test_download_activation_failure_keeps_model_inactive(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    runtime.model_downloader = _Downloader(tmp_path / "models" / "broken.gguf")
    model_id = BUILTIN_MODELS[0].model_id
    monkeypatch.setattr(
        desktop_http,
        "describe_model",
        lambda *args, **kwargs: ModelDescriptor(
            model_id=model_id,
            display_name="Broken Model",
            gguf_path=None,
            source="test",
            status="needs_config",
            backend="llama_cpp",
        ),
    )
    monkeypatch.setattr(
        desktop_http,
        "_load_local_model_backend",
        lambda _runtime, _model: (_ for _ in ()).throw(RuntimeError("load failed")),
    )
    client = create_desktop_app(runtime).test_client()

    client.post("/api/models/download", json={"model_id": model_id})
    assert _wait_for_completion(client, model_id)["state"] == "completed"

    assert runtime.local_available is False
    assert runtime.backend_mode == "no_backend"
    assert runtime.orchestrator.backend.label == "desktop"
    assert not (tmp_path / "settings.json").exists()
