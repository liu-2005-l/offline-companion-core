from __future__ import annotations

from pathlib import Path

import pytest

from offline_companion.runtime.inference_backend import (
    EchoBackend,
    LlamaCppBackend,
    resolve_gguf_path,
)
from offline_companion.runtime.inference_backend.backend import strip_model_output
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.shared.types import MessageRow, ModelRuntimeConfig


def test_resolve_gguf_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InferenceBackendError) as exc_info:
        resolve_gguf_path(tmp_path / "nope.gguf")
    assert "nope.gguf" in str(exc_info.value)


def test_resolve_gguf_wrong_suffix(tmp_path: Path) -> None:
    f = tmp_path / "model.bin"
    f.write_bytes(b"x")
    with pytest.raises(InferenceBackendError, match="gguf"):
        resolve_gguf_path(f)


def test_check_model_missing_file() -> None:
    report = LlamaCppBackend.check_model("/nonexistent/path/model.gguf", load_model=False)
    assert not report.ok
    assert "model.gguf" in report.message


def test_check_model_load_model_false_on_valid_path(tmp_path: Path) -> None:
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"FAKE")
    report = LlamaCppBackend.check_model(gguf, load_model=False)
    if report.ok:
        assert "llama" in report.message.lower() or "??" in report.message or "??" in report.message
    else:
        assert "llama" in report.message.lower() or "??" in report.message


def test_echo_backend_health_check() -> None:
    report = EchoBackend("test").health_check()
    assert report.ok
    assert report.backend == "echo"


def test_llama_generate_merges_memory_into_single_system_message(tmp_path: Path) -> None:
    """????????? system????? system ? chat ?????"""
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"FAKE")
    backend = LlamaCppBackend(gguf, skip_load=True)
    captured: dict[str, object] = {}

    class _FakeLlama:
        def create_chat_completion(self, *, messages, max_tokens, stop=None):
            captured["messages"] = messages
            captured["stop"] = stop
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


def test_llama_generate_downgrades_system_role_when_model_disables_it(tmp_path: Path) -> None:
    """??? system role ??????????????? user ???"""
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"FAKE")
    backend = LlamaCppBackend(
        gguf,
        skip_load=True,
        model_config=ModelRuntimeConfig(model_id="test", supports_system_role=False),
    )
    captured: dict[str, object] = {}

    class _FakeLlama:
        def create_chat_completion(self, *, messages, max_tokens, stop=None):
            captured["messages"] = messages
            return {"choices": [{"message": {"content": "ok"}}]}

    backend._llama = _FakeLlama()
    backend.generate(
        system_prompt="sys",
        history=[],
        user_message="q",
        memory_block="",
        max_tokens=8,
    )
    msgs = captured["messages"]
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "sys"


def test_llama_backend_applies_stop_tokens_and_strips_tags(tmp_path: Path) -> None:
    """C1 ????????? stop_tokens???????????"""
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"FAKE")
    backend = LlamaCppBackend(
        gguf,
        skip_load=True,
        model_config=ModelRuntimeConfig(
            model_id="test",
            stop_tokens=("<stop>",),
            strip_output_tags=("think",),
        ),
    )
    captured: dict[str, object] = {}

    class _FakeLlama:
        def create_chat_completion(self, *, messages, max_tokens, stop=None):
            captured["stop"] = stop
            return {"choices": [{"message": {"content": "<think>hidden</think>visible"}}]}

    backend._llama = _FakeLlama()
    result = backend.generate(
        system_prompt="sys",
        history=[],
        user_message="q",
        memory_block="",
        max_tokens=8,
    )

    assert result == "visible"
    assert captured["stop"] == ["<stop>"]


def test_strip_model_output_supports_prefix_style_labels() -> None:
    """????????????????"""
    result = strip_model_output(
        "think: keep only final answer",
        ModelRuntimeConfig(model_id="test", strip_output_tags=("think",)),
    )
    assert result == "keep only final answer"


def test_create_llama_backend_raises_on_bad_path() -> None:
    from offline_companion.runtime.inference_backend import create_llama_backend

    with pytest.raises(InferenceBackendError):
        create_llama_backend("/no/such/model.gguf", run_health_check=True)
