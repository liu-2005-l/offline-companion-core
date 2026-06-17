"""models/registry.yaml 默认模型解析。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.shared.runtime_paths import dev_repo_root, models_dir
from offline_companion.shell.ui_host.model_registry import (
    load_registry,
    resolve_default_gguf_path,
    resolve_n_gpu_layers,
)


def test_resolve_from_registry(tmp_path, monkeypatch) -> None:
    models = tmp_path / "models"
    models.mkdir()
    gguf = models / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
    gguf.write_bytes(b"fake")
    (models / "registry.yaml").write_text(
        """
active: qwen2.5-1.5b-instruct-q4_k_m
entries:
  - id: qwen2.5-1.5b-instruct-q4_k_m
    file: Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("OFFLINE_COMPANION_MODELS_DIR", str(models))
    resolved = resolve_default_gguf_path()
    assert resolved == gguf.resolve()


def test_resolve_single_gguf_without_registry(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OFFLINE_COMPANION_GGUF", raising=False)
    repo = dev_repo_root() / "models"
    if (repo / "registry.yaml").is_file():
        monkeypatch.setenv("OFFLINE_COMPANION_MODELS_DIR", str(tmp_path / "models"))
    models = tmp_path / "models"
    models.mkdir()
    only = models / "solo.gguf"
    only.write_bytes(b"x")
    assert resolve_default_gguf_path(data_root_override=tmp_path) == only.resolve()


def test_resolve_env_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OFFLINE_COMPANION_MODELS_DIR", str(tmp_path / "models"))
    gguf = tmp_path / "models" / "from_env.gguf"
    gguf.parent.mkdir()
    gguf.write_bytes(b"x")
    monkeypatch.setenv("OFFLINE_COMPANION_GGUF", str(gguf))
    assert resolve_default_gguf_path(data_root_override=tmp_path) == gguf.resolve()


def test_resolve_n_gpu_layers_env(monkeypatch) -> None:
    monkeypatch.setenv("OFFLINE_COMPANION_N_GPU_LAYERS", "99")
    assert resolve_n_gpu_layers(0) == 99
    assert resolve_n_gpu_layers(20) == 20


def test_repo_registry_template() -> None:
    reg = dev_repo_root() / "models" / "registry.yaml"
    assert reg.is_file()
    assert models_dir() == dev_repo_root() / "models"
    data = load_registry()
    assert data.get("active") == "qwen2.5-1.5b-instruct-q4_k_m"
