"""models/registry.yaml ???????"""

from __future__ import annotations

from offline_companion.shared import runtime_paths
from offline_companion.shared.runtime_paths import dev_repo_root, models_dir
from offline_companion.shared.types import CapabilityTag
from offline_companion.shell.ui_host.model_registry import (
    describe_model,
    discover_models,
    load_model_config,
    load_registry,
    resolve_default_gguf_path,
    resolve_default_model_config,
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


def test_frozen_models_dir_prefers_installed_model(tmp_path, monkeypatch) -> None:
    install_dir = tmp_path / "Offline Companion"
    installed_models = install_dir / "models"
    installed_models.mkdir(parents=True)
    (installed_models / "bundled.gguf").write_bytes(b"GGUF")
    monkeypatch.setattr(runtime_paths, "_is_frozen", lambda: True)
    monkeypatch.setattr(runtime_paths.sys, "executable", str(install_dir / "OfflineCompanion.exe"))

    assert models_dir() == installed_models


def test_frozen_models_dir_falls_back_to_data_root(tmp_path, monkeypatch) -> None:
    install_dir = tmp_path / "Offline Companion"
    install_dir.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(runtime_paths, "_is_frozen", lambda: True)
    monkeypatch.setattr(runtime_paths.sys, "executable", str(install_dir / "OfflineCompanion.exe"))
    monkeypatch.setenv("OFFLINE_COMPANION_DATA_DIR", str(data))

    assert models_dir() == data / "models"


def test_model_config_loads_chat_template_and_stop_tokens() -> None:
    """??????? Jinja2 chat_template?stop_tokens ????????"""
    cfg = load_model_config("qwen2.5-1.5b-instruct-q4_k_m")
    assert "<|im_start|>" in cfg.chat_template
    assert "<|im_end|>" in cfg.stop_tokens
    assert "think" in cfg.strip_output_tags
    assert cfg.capability_profile is CapabilityTag.SIMPLE_QA
    assert cfg.n_ctx == 4096


def test_resolve_default_model_config_from_registry() -> None:
    """????????? registry active ??"""
    cfg = resolve_default_model_config()
    assert cfg is not None
    assert cfg.model_id == "qwen2.5-1.5b-instruct-q4_k_m"


def test_describe_model_reports_ready_status(tmp_path, monkeypatch) -> None:
    """在临时模型目录与配置目录齐备时返回 ready。"""
    model_id = "qwen2.5-1.5b-instruct-q4_k_m"
    models = tmp_path / "models"
    configs = tmp_path / "configs" / "models"
    models.mkdir()
    configs.mkdir(parents=True)
    gguf = models / f"{model_id}.gguf"
    gguf.write_bytes(b"fake")
    (configs / f"{model_id}.yaml").write_text(
        """
display_name: Qwen2.5 1.5B Instruct Q4_K_M
backend: llama_cpp
n_ctx: 4096
supports_system_role: true
chat_template: |
  {% for message in messages %}
  {{ message['role'] }}: {{ message['content'] }}
  {% endfor %}
capability_profile: simple_qa
strip_output_tags:
  - think
stop_tokens:
  - <|im_end|>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("OFFLINE_COMPANION_MODELS_DIR", str(models))
    monkeypatch.setenv("OFFLINE_COMPANION_CONFIGS_DIR", str(tmp_path / "configs"))
    descriptor = describe_model(model_id)
    assert descriptor.status == "ready"
    assert descriptor.gguf_path == str(gguf.resolve())
    assert descriptor.display_name.startswith("Qwen2.5 1.5B")


def test_describe_model_without_yaml_needs_config(tmp_path, monkeypatch) -> None:
    """??? GGUF ??? YAML ?????? needs_config?"""
    models = tmp_path / "models"
    models.mkdir()
    gguf = models / "demo-q4.gguf"
    gguf.write_bytes(b"x")
    monkeypatch.setenv("OFFLINE_COMPANION_MODELS_DIR", str(models))
    descriptor = describe_model("demo-q4")
    assert descriptor.status == "needs_config"
    assert "chat_template" in descriptor.missing_fields
    assert descriptor.gguf_path == str(gguf.resolve())


def test_discover_models_includes_yaml_only_entries() -> None:
    """discover_models ?????? YAML ??????"""
    model_ids = {item.model_id for item in discover_models()}
    assert "qwen2.5-1.5b-instruct-q4_k_m" in model_ids
    assert "qwen2.5-7b-instruct-q4_k_m" in model_ids
