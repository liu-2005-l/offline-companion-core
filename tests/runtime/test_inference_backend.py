from __future__ import annotations

from pathlib import Path

import pytest

from offline_companion.runtime.inference_backend import (
    EchoBackend,
    LlamaCppBackend,
    resolve_gguf_path,
)
from offline_companion.shared.errors import InferenceBackendError


def test_resolve_gguf_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InferenceBackendError, match="不存在"):
        resolve_gguf_path(tmp_path / "nope.gguf")


def test_resolve_gguf_wrong_suffix(tmp_path: Path) -> None:
    f = tmp_path / "model.bin"
    f.write_bytes(b"x")
    with pytest.raises(InferenceBackendError, match="gguf"):
        resolve_gguf_path(f)


def test_check_model_missing_file() -> None:
    report = LlamaCppBackend.check_model("/nonexistent/path/model.gguf", load_model=False)
    assert not report.ok
    assert "不存在" in report.message or "模型" in report.message


def test_check_model_load_model_false_on_valid_path(tmp_path: Path) -> None:
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"FAKE")  # 仅用于路径后缀检查
    report = LlamaCppBackend.check_model(gguf, load_model=False)
    # 无 llama-cpp 时会在 import 阶段失败；有则路径+import 通过
    if report.ok:
        assert "通过" in report.message or "就绪" in report.message
    else:
        assert "llama" in report.message.lower() or "安装" in report.message


def test_echo_backend_health_check() -> None:
    report = EchoBackend("test").health_check()
    assert report.ok
    assert report.backend == "echo"


def test_create_llama_backend_raises_on_bad_path() -> None:
    from offline_companion.runtime.inference_backend import create_llama_backend

    with pytest.raises(InferenceBackendError):
        create_llama_backend("/no/such/model.gguf", run_health_check=True)
