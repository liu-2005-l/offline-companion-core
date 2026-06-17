"""model_registry：本地 GGUF 登记与默认模型解析（A1；不下载）。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from offline_companion.shared.runtime_paths import models_dir


def registry_path(*, data_root_override: Path | None = None) -> Path:
    """摘要：``registry.yaml`` 路径。"""
    return models_dir(data_root_override=data_root_override) / "registry.yaml"


def load_registry(*, data_root_override: Path | None = None) -> dict:
    """摘要：加载模型登记文件；不存在时返回空 dict。"""
    path = registry_path(data_root_override=data_root_override)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def resolve_default_gguf_path(*, data_root_override: Path | None = None) -> Path | None:
    """摘要：解析默认 GGUF 路径（不含 CLI ``--model`` 显式覆盖）。

    优先级：
        ``registry.yaml`` 的 ``active`` 条目 →
        ``models/`` 下唯一 ``*.gguf`` →
        ``OFFLINE_COMPANION_GGUF`` 环境变量。

    参数：
        data_root_override: 与 ``--data-dir`` 对齐的数据根。

    返回值：
        存在的 ``.gguf`` 绝对路径；无法解析时 ``None``（由调用方回落 Echo）。
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
    """摘要：CLI ``--n-gpu-layers`` 为 0 时，可读环境变量覆盖。"""
    if cli_value != 0:
        return cli_value
    env = os.environ.get("OFFLINE_COMPANION_N_GPU_LAYERS")
    if not env:
        return cli_value
    try:
        return int(env)
    except ValueError:
        return cli_value
