"""模型 SHA256 完整性校验与事件测试。"""

import hashlib

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.shell.ui_host.model_downloader import ModelDownloader
from offline_companion.shell.ui_host.model_registry import ModelDirectory, ModelEntry


def make_entry(data: bytes) -> ModelEntry:
    return ModelEntry(
        model_id="verified-model",
        display_name="Verified Model",
        family="test",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        quant="Q4_K_M",
        context_length=4096,
        recommended=False,
        description="test",
        download_urls=("https://source.test/model",),
        min_ram_mb=1,
    )


def make_downloader(tmp_path, entry: ModelEntry, stream: EventStream | None = None) -> ModelDownloader:
    return ModelDownloader((entry,), ModelDirectory(tmp_path), stream, retry_backoff_base=0)


def test_verify_local_model_accepts_matching_sha256(tmp_path) -> None:
    data = b"valid-model"
    entry = make_entry(data)
    path = ModelDirectory(tmp_path).model_path(entry.model_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    assert make_downloader(tmp_path, entry).verify_local_model(entry.model_id) is True


def test_verify_local_model_rejects_truncated_file_and_emits_failure(tmp_path) -> None:
    entry = make_entry(b"valid-model")
    path = ModelDirectory(tmp_path).model_path(entry.model_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"valid")
    stream = EventStream("verification", build_default_registry())

    assert make_downloader(tmp_path, entry, stream).verify_local_model(entry.model_id) is False
    event = stream.get_events()[-1]
    assert event.event_type == "model/verification_failed"
    assert event.payload["expected"] == entry.sha256
    assert event.payload["actual"] != entry.sha256


def test_verify_local_model_rejects_missing_file_without_crashing(tmp_path) -> None:
    entry = make_entry(b"valid-model")
    stream = EventStream("verification", build_default_registry())

    assert make_downloader(tmp_path, entry, stream).verify_local_model(entry.model_id) is False
    assert stream.get_events()[-1].payload["actual"] is None


def test_verify_local_model_emits_verified_event(tmp_path) -> None:
    data = b"valid-model"
    entry = make_entry(data)
    path = ModelDirectory(tmp_path).model_path(entry.model_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    stream = EventStream("verification", build_default_registry())

    assert make_downloader(tmp_path, entry, stream).verify_local_model(entry.model_id) is True
    assert stream.get_events()[-1].event_type == "model/verified"
