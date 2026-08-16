"""模型下载管理 API 与进度 SSE 测试。"""

import time
from pathlib import Path

from tests.test_desktop_http import _runtime

from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
from offline_companion.shell.ui_host.model_downloader import DownloadProgress, DownloadState
from offline_companion.shell.ui_host.model_registry import BUILTIN_MODELS


class FakeDownloader:
    def __init__(self, tmp_path: Path) -> None:
        self.progress: DownloadProgress | None = None
        self.cancelled: list[str] = []
        self.path = tmp_path / "model.gguf"

    def get_progress(self, model_id: str):
        return self.progress if self.progress and self.progress.model_id == model_id else None

    def download(self, model_id: str):
        self.progress = DownloadProgress(
            model_id, DownloadState.COMPLETED, 10, 10, 1.0, None, "https://test", 1, 0
        )
        return self.path

    def cancel(self, model_id: str) -> None:
        self.cancelled.append(model_id)
        if self.progress is not None:
            self.progress = DownloadProgress(
                model_id,
                DownloadState.CANCELLED,
                self.progress.downloaded_bytes,
                self.progress.total_bytes,
                self.progress.speed_bytes_per_sec,
                None,
                self.progress.source_url,
                self.progress.attempt,
                self.progress.source_index,
            )


def test_download_api_starts_and_reports_status(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.model_downloader = FakeDownloader(tmp_path)
    client = create_desktop_app(runtime).test_client()
    model_id = BUILTIN_MODELS[0].model_id

    response = client.post("/api/models/download", json={"model_id": model_id})
    assert response.status_code == 202
    for _ in range(20):
        status = client.get("/api/models/download/status").get_json()
        if status["items"] and status["items"][0]["state"] == "completed":
            break
        time.sleep(0.01)
    assert status["items"][0]["state"] == "completed"


def test_download_api_cancel_and_sse_terminal_event(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    fake = FakeDownloader(tmp_path)
    runtime.model_downloader = fake
    client = create_desktop_app(runtime).test_client()
    model_id = BUILTIN_MODELS[0].model_id
    fake.progress = DownloadProgress(
        model_id, DownloadState.DOWNLOADING, 2, 10, 1.0, None, "https://test", 1, 0
    )

    cancelled = client.post("/api/models/download/cancel", json={"model_id": model_id})
    assert cancelled.get_json()["status"] == "cancel_requested"
    stream = client.get(f"/api/models/download/events?model_id={model_id}")
    assert stream.status_code == 200
    assert b"model/download_progress" in stream.data
    assert b"cancelled" in stream.data
