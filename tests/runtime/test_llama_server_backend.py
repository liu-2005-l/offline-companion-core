from __future__ import annotations

import json
from pathlib import Path

import pytest

from offline_companion.runtime.inference_backend.llama_server_backend import (
    LlamaServerBackend,
    check_llama_server_model,
)
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.shared.types import MessageRow, ModelRuntimeConfig


def _model_file(tmp_path: Path) -> Path:
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF")
    return path


def test_generate_posts_openai_messages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    backend = LlamaServerBackend(
        _model_file(tmp_path),
        model_config=ModelRuntimeConfig(
            model_id="test",
            stop_tokens=("<stop>",),
        ),
    )
    monkeypatch.setattr(backend, "start", lambda: None)
    captured: dict[str, object] = {}

    def fake_post(path: str, payload: dict[str, object]) -> dict[str, object]:
        captured.update({"path": path, "payload": payload})
        return {"choices": [{"message": {"content": " 回答 "}}]}

    monkeypatch.setattr(backend, "_post_json", fake_post)
    result = backend.generate(
        system_prompt="系统",
        history=[
            MessageRow(
                role="assistant",
                content="历史",
                created_at="2026-07-30T00:00:00Z",
                meta={},
            )
        ],
        user_message="问题",
        memory_block="记忆",
    )

    assert result == "回答"
    assert captured["path"] == "/v1/chat/completions"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["stop"] == ["<stop>"]
    assert payload["messages"] == [
        {"role": "system", "content": "系统\n\n记忆"},
        {"role": "assistant", "content": "历史"},
        {"role": "user", "content": "问题"},
    ]


def test_post_json_wraps_connection_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = LlamaServerBackend(_model_file(tmp_path))

    def fail(*args: object, **kwargs: object) -> object:
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(InferenceBackendError, match="请求失败"):
        backend._post_json("/v1/chat/completions", json.loads("{}"))


def test_generate_restarts_once_after_sidecar_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = LlamaServerBackend(_model_file(tmp_path))
    monkeypatch.setattr(backend, "start", lambda: None)
    events: list[str] = []
    attempts = {"count": 0}

    class _ExitedProcess:
        returncode = 7

        def poll(self) -> int:
            return self.returncode

    backend._process = _ExitedProcess()  # type: ignore[assignment]
    monkeypatch.setattr(backend, "_log_sidecar_event", events.append)

    def fake_post(_path: str, _payload: dict[str, object]) -> dict[str, object]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise InferenceBackendError("connection lost")
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(backend, "_post_json", fake_post)

    assert backend.generate(system_prompt="", history=[], user_message="hi", memory_block="") == "ok"
    assert attempts["count"] == 2
    assert events == ["llama-server 异常退出，退出码: 7"]


def test_check_model_reports_server_start_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_health(self: LlamaServerBackend):
        raise InferenceBackendError("server missing")

    monkeypatch.setattr(LlamaServerBackend, "health_check", fail_health)
    report = check_llama_server_model(_model_file(tmp_path))

    assert not report.ok
    assert report.backend == "llama_server"
    assert "server missing" in report.message
