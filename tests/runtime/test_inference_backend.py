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


def test_llama_generate_merges_memory_into_single_system_message(tmp_path: Path) -> None:
    """记忆块应并入同一条 system，避免多条 system 被 chat 模板丢弃。"""
    from offline_companion.runtime.inference_backend.backend import LlamaCppBackend
    from offline_companion.shared.types import MessageRow

    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"FAKE")
    backend = LlamaCppBackend(gguf, skip_load=True)
    captured: dict[str, object] = {}

    class _FakeLlama:
        def create_chat_completion(self, *, messages, max_tokens):
            captured["messages"] = messages
            return {"choices": [{"message": {"content": "ok"}}]}

    backend._llama = _FakeLlama()
    backend.generate(
        system_prompt="sys",
        history=[MessageRow(role="user", content="hi", created_at=0.0, meta={})],
        user_message="q",
        memory_block="mem-block",
        max_tokens=8,
    )
    msgs = captured["messages"]
    assert isinstance(msgs, list)
    assert len(msgs) == 3
    assert msgs[0]["role"] == "system"
    assert "sys" in msgs[0]["content"]
    assert "mem-block" in msgs[0]["content"]
    assert all(m["role"] != "system" or i == 0 for i, m in enumerate(msgs))


def test_create_llama_backend_raises_on_bad_path() -> None:
    from offline_companion.runtime.inference_backend import create_llama_backend

    with pytest.raises(InferenceBackendError):
        create_llama_backend("/no/such/model.gguf", run_health_check=True)
