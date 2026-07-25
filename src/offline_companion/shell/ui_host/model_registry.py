"""model_registry：本地 GGUF 注册与默认模型解析（A1；不下载）。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from offline_companion.shared.runtime_paths import configs_dir, dev_repo_root, models_dir
from offline_companion.shared.types import ModelRuntimeConfig


def registry_path(*, data_root_override: Path | None = None) -> Path:
    """摘要：返回 `registry.yaml` 路径。"""
    return models_dir(data_root_override=data_root_override) / "registry.yaml"


def load_registry(*, data_root_override: Path | None = None) -> dict:
    """摘要：加载模型注册文件；不存在时返回空字典。"""
    path = registry_path(data_root_override=data_root_override)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def model_config_path(model_id: str) -> Path:
    """摘要：返回模型配置 YAML 路径。"""
    safe_id = (model_id or "").strip()
    primary = configs_dir() / "models" / f"{safe_id}.yaml"
    if primary.is_file():
        return primary
    return dev_repo_root() / "configs" / "models" / f"{safe_id}.yaml"


def load_model_config(model_id: str) -> ModelRuntimeConfig:
    """摘要：加载模型运行时配置；缺失时返回空配置。"""
    safe_id = (model_id or "").strip()
    if not safe_id:
        return ModelRuntimeConfig(model_id="")
    path = model_config_path(safe_id)
    if not path.is_file():
        return ModelRuntimeConfig(model_id=safe_id)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = raw if isinstance(raw, dict) else {}
    stop_tokens = data.get("stop_tokens") or ()
    strip_tags = data.get("strip_output_tags") or ()
    return ModelRuntimeConfig(
        model_id=str(data.get("id") or safe_id),
        chat_template=str(data.get("chat_template") or ""),
        stop_tokens=tuple(str(item) for item in stop_tokens if str(item)),
        strip_output_tags=tuple(str(item) for item in strip_tags if str(item)),
    )


def resolve_active_model_id(*, data_root_override: Path | None = None) -> str | None:
    """摘要：解析 `registry.yaml` 中的活动模型 ID。"""
    active_id = str(load_registry(data_root_override=data_root_override).get("active") or "").strip()
    return active_id or None


def resolve_default_model_config(*, data_root_override: Path | None = None) -> ModelRuntimeConfig | None:
    """摘要：解析默认模型对应的运行时配置。"""
    active_id = resolve_active_model_id(data_root_override=data_root_override)
    if not active_id:
        return None
    return load_model_config(active_id)


def resolve_default_gguf_path(*, data_root_override: Path | None = None) -> Path | None:
    """摘要：解析默认 GGUF 路径。

    参数：
        data_root_override: 与 `--data-dir` 对齐的数据根。

    返回：
        存在的 `.gguf` 绝对路径；无法解析时返回 `None`。
    """
    root = models_dir(data_root_override=data_root_override)

    reg = load_registry(data_root_override=data_root_override)
    active_id = reg.get("active")
    entries = reg.get("entries") or []
    if active_id and isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            if item.get("id") != active_id:
                continue
            file_name = str(item.get("file") or "").strip()
            if not file_name:
                break
            candidate = root / file_name
            if candidate.is_file():
                return candidate.resolve()
            break

    ggufs = sorted(root.glob("*.gguf"))
    if len(ggufs) == 1:
        return ggufs[0].resolve()

    env = os.environ.get("OFFLINE_COMPANION_GGUF")
    if env:
        candidate = Path(env).expanduser().resolve()
        if candidate.is_file():
            return candidate

    return None


def resolve_n_gpu_layers(cli_value: int) -> int:
    """摘要：CLI `--n-gpu-layers` 为 0 时，允许环境变量覆盖。"""
    if cli_value != 0:
        return cli_value
    env = os.environ.get("OFFLINE_COMPANION_N_GPU_LAYERS")
    if not env:
        return cli_value
    try:
        return int(env)
    except ValueError:
        return cli_value
