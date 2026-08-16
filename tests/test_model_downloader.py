"""模型下载器的断点、重试、校验、取消与事件流测试。"""

import hashlib
import os
import time
import urllib.error

import pytest

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.shell.ui_host.model_downloader import (
    DownloadCancelled,
    DownloadState,
    ModelDownloader,
)
from offline_companion.shell.ui_host.model_registry import ModelDirectory, ModelEntry


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body)
        body, self._body = self._body[:size], self._body[size:]
        return body


def make_entry(data: bytes, *, urls: tuple[str, ...] = ("https://source.test/model",)) -> ModelEntry:
    return ModelEntry(
        model_id="test-model",
        display_name="Test Model",
        family="test",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        quant="Q4_K_M",
        context_length=4096,
        recommended=False,
        description="test",
        download_urls=urls,
        min_ram_mb=1,
    )


def test_download_verifies_atomically_and_emits_events(tmp_path, monkeypatch) -> None:
    data = b"model-data"
    entry = make_entry(data)
    stream = EventStream("downloads", build_default_registry())
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(data),
    )
    downloader = ModelDownloader(
        (entry,),
        ModelDirectory(tmp_path),
        stream,
        retry_backoff_base=0,
        chunk_size=3,
    )

    result = downloader.download(entry.model_id)

    assert result.read_bytes() == data
    assert not result.with_suffix(result.suffix + ".tmp").exists()
    assert downloader.get_progress(entry.model_id).state is DownloadState.COMPLETED
    assert [event.event_type for event in stream.get_events()] == [
        "model/download_started",
        "model/download_progress",
        "model/download_progress",
        "model/download_progress",
        "model/download_progress",
        "model/download_completed",
    ]


def test_download_resumes_with_range_header(tmp_path, monkeypatch) -> None:
    data = b"abcdefghij"
    entry = make_entry(data)
    directory = ModelDirectory(tmp_path)
    directory.ensure_dir()
    temp_path = directory.model_path(entry.model_id).with_suffix(".gguf.tmp")
    temp_path.write_bytes(data[:4])
    requests = []

    def open_url(request, **_kwargs):
        requests.append(request)
        return FakeResponse(data[4:], status=206)

    monkeypatch.setattr("urllib.request.urlopen", open_url)
    downloader = ModelDownloader((entry,), directory, retry_backoff_base=0)

    assert downloader.download(entry.model_id).read_bytes() == data
    assert requests[0].headers["Range"] == "bytes=4-"


def test_download_falls_back_to_second_source(tmp_path, monkeypatch) -> None:
    data = b"fallback"
    entry = make_entry(data, urls=("https://first.test/model", "https://second.test/model"))
    calls = []

    def open_url(request, **_kwargs):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.URLError("offline")
        return FakeResponse(data)

    monkeypatch.setattr("urllib.request.urlopen", open_url)
    downloader = ModelDownloader((entry,), ModelDirectory(tmp_path), max_retries=1, retry_backoff_base=0)

    assert downloader.download(entry.model_id).read_bytes() == data
    assert calls == list(entry.download_urls)


def test_download_retries_and_reports_failure(tmp_path, monkeypatch) -> None:
    entry = make_entry(b"expected")
    attempts = []

    def fail(_request, **_kwargs):
        attempts.append(True)
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    downloader = ModelDownloader((entry,), ModelDirectory(tmp_path), max_retries=3, retry_backoff_base=0)

    with pytest.raises(RuntimeError, match="所有下载源均失败"):
        downloader.download(entry.model_id)

    assert len(attempts) == 3
    assert downloader.get_progress(entry.model_id).state is DownloadState.FAILED


def test_cancel_preserves_partial_file_and_reports_cancelled(tmp_path, monkeypatch) -> None:
    data = b"cancel-me"
    entry = make_entry(data)
    downloader = ModelDownloader((entry,), ModelDirectory(tmp_path), retry_backoff_base=0, chunk_size=2)

    def open_url(*_args, **_kwargs):
        return FakeResponse(data)

    monkeypatch.setattr("urllib.request.urlopen", open_url)

    def cancel_on_progress(progress):
        if progress.state is DownloadState.DOWNLOADING and progress.downloaded_bytes:
            downloader.cancel(entry.model_id)

    with pytest.raises(DownloadCancelled):
        downloader.download(entry.model_id, cancel_on_progress)

    assert downloader.get_progress(entry.model_id).state is DownloadState.CANCELLED
    assert ModelDirectory(tmp_path).model_path(entry.model_id).with_suffix(".gguf.tmp").exists()


def test_cleanup_stale_temp_files_removes_old_downloads_but_keeps_recent(tmp_path) -> None:
    directory = ModelDirectory(tmp_path)
    directory.ensure_dir()
    old_path = directory.model_path("old").with_suffix(".gguf.tmp")
    recent_path = directory.model_path("recent").with_suffix(".gguf.tmp")
    old_path.write_bytes(b"old")
    recent_path.write_bytes(b"recent")
    old_timestamp = time.time() - 3600
    os.utime(old_path, (old_timestamp, old_timestamp))
    downloader = ModelDownloader((), directory)

    removed = downloader.cleanup_stale_temp_files(max_age_seconds=60)

    assert removed == [old_path]
    assert not old_path.exists()
    assert recent_path.exists()


def test_download_fails_before_network_when_disk_space_is_insufficient(tmp_path, monkeypatch) -> None:
    entry = make_entry(b"expected")
    calls = []
    monkeypatch.setattr(
        "offline_companion.shell.ui_host.model_downloader.shutil.disk_usage",
        lambda _path: type("Usage", (), {"free": 0})(),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: calls.append(True))
    downloader = ModelDownloader((entry,), ModelDirectory(tmp_path), retry_backoff_base=0)

    with pytest.raises(RuntimeError, match="磁盘空间不足"):
        downloader.download(entry.model_id)

    assert calls == []
    assert downloader.get_progress(entry.model_id).state is DownloadState.FAILED
