"""????? GGUF ?????????????A1??????"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from offline_companion.shared.runtime_paths import configs_dir, dev_repo_root, models_dir
from offline_companion.shared.types import (
    CapabilityProfile,
    CapabilityTag,
    ModelDescriptor,
    ModelRuntimeConfig,
)

_SUPPORTED_ARCHITECTURES = {"qwen2", "qwen2moe", "llama", "mistral", "gemma"}
_REQUIRED_CONFIG_FIELDS = ("chat_template", "n_ctx", "capability_profile")


@dataclass(frozen=True)
class ModelEntry:
    """摘要：描述可供首次引导选择的本地模型及其下载元数据。"""

    model_id: str
    display_name: str
    family: str
    size_bytes: int
    sha256: str
    quant: str
    context_length: int
    recommended: bool
    description: str
    download_urls: tuple[str, ...]
    min_ram_mb: int


BUILTIN_MODELS: tuple[ModelEntry, ...] = (
    ModelEntry(
        model_id="qwen2.5-1.5b-instruct-q4_k_m",
        display_name="Qwen2.5 1.5B (Q4_K_M)",
        family="qwen2.5",
        size_bytes=1_117_320_736,
        sha256="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        quant="Q4_K_M",
        context_length=4096,
        recommended=True,
        description="推荐配置，约 1.1GB，普通电脑可流畅运行",
        download_urls=(
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        ),
        min_ram_mb=2048,
    ),
)


class ModelDirectory:
    """摘要：管理数据根目录下的 GGUF 模型文件。"""

    def __init__(self, data_root: Path) -> None:
        """摘要：创建模型目录访问器。

        参数：
            data_root: 应用数据根目录。
        """
        self.models_dir = models_dir(data_root_override=data_root)

    def model_path(self, model_id: str) -> Path:
        """摘要：返回指定模型的安全文件路径。

        参数：
            model_id: 注册表中的模型 ID。
        返回值：
            模型 GGUF 文件路径。
        """
        safe_id = (model_id or "").strip()
        if not safe_id or Path(safe_id).name != safe_id:
            raise ValueError("模型 ID 无效")
        return self.models_dir / f"{safe_id}.gguf"

    def is_downloaded(self, model_id: str) -> bool:
        """摘要：判断模型文件是否存在且非空。"""
        path = self.model_path(model_id)
        return path.is_file() and path.stat().st_size > 0

    def list_local_models(self) -> list[str]:
        """摘要：列出模型目录中已存在的非空 GGUF 文件 ID。"""
        if not self.models_dir.is_dir():
            return []
        return sorted(
            path.stem
            for path in self.models_dir.glob("*.gguf")
            if path.is_file() and path.stat().st_size > 0
        )

    def ensure_dir(self) -> None:
        """摘要：确保模型目录存在。"""
        self.models_dir.mkdir(parents=True, exist_ok=True)


def builtin_model_payload(entry: ModelEntry, directory: ModelDirectory) -> dict[str, object]:
    """摘要：将内置模型元数据转换为 API 安全 payload。"""
    payload = asdict(entry)
    payload["download_urls"] = list(entry.download_urls)
    payload["downloaded"] = directory.is_downloaded(entry.model_id)
    return payload


def registry_path(*, data_root_override: Path | None = None) -> Path:
    """????? `registry.yaml` ???"""
    return models_dir(data_root_override=data_root_override) / "registry.yaml"


def load_registry(*, data_root_override: Path | None = None) -> dict:
    """??????????????????????"""
    path = registry_path(data_root_override=data_root_override)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def model_config_path(model_id: str) -> Path:
    """????????? YAML ???"""
    safe_id = (model_id or "").strip()
    primary = configs_dir() / "models" / f"{safe_id}.yaml"
    if primary.is_file():
        return primary
    return dev_repo_root() / "configs" / "models" / f"{safe_id}.yaml"


def load_model_config_data(model_id: str) -> dict[str, object]:
    """??????? YAML ???????"""
    safe_id = (model_id or "").strip()
    if not safe_id:
        return {}
    path = model_config_path(safe_id)
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def load_model_config(model_id: str) -> ModelRuntimeConfig:
    """??????????????????????"""
    safe_id = (model_id or "").strip()
    if not safe_id:
        return ModelRuntimeConfig(model_id="")
    return runtime_config_from_descriptor(describe_model(safe_id))


def runtime_config_from_descriptor(descriptor: ModelDescriptor) -> ModelRuntimeConfig:
    """???????????????????"""
    return ModelRuntimeConfig(
        model_id=descriptor.model_id,
        display_name=descriptor.display_name,
        backend=descriptor.backend,
        architecture=descriptor.architecture,
        n_ctx=descriptor.n_ctx,
        supports_system_role=descriptor.supports_system_role,
        add_bos_token=descriptor.add_bos_token,
        eos_token=descriptor.eos_token,
        chat_template=descriptor.chat_template,
        stop_tokens=descriptor.stop_tokens,
        strip_output_tags=descriptor.strip_output_tags,
        capability_profile=descriptor.capability_profile,
        default_params=dict(descriptor.default_params),
        moe=None if descriptor.moe is None else dict(descriptor.moe),
    )


def describe_model(model_id: str, *, data_root_override: Path | None = None) -> ModelDescriptor:
    """????? GGUF ????? YAML ????????????"""
    safe_id = (model_id or "").strip()
    if not safe_id:
        return ModelDescriptor(
            model_id="",
            display_name="",
            gguf_path=None,
            source="manual_config",
            status="needs_config",
            backend="llama_cpp",
            missing_fields=("model_id",),
        )
    config = load_model_config_data(safe_id)
    gguf = _find_gguf_for_model(safe_id, data_root_override=data_root_override)
    source = "manual_config" if config else "auto_discovered"
    display_name = str(config.get("display_name") or safe_id)
    backend = str(config.get("backend") or "llama_cpp")
    architecture = _normalize_optional_str(config.get("architecture"))
    n_ctx = _normalize_optional_int(config.get("n_ctx"))
    supports_system_role = bool(config.get("supports_system_role", True))
    add_bos_token = bool(config.get("add_bos_token", False))
    eos_token = _normalize_optional_str(config.get("eos_token"))
    chat_template = str(config.get("chat_template") or "")
    stop_tokens = _tuple_of_str(config.get("stop_tokens"))
    strip_tags = _tuple_of_str(config.get("strip_output_tags"))
    raw_capability_profile = config.get("capability_profile")
    capability_profile = (
        _normalize_capability_profile(raw_capability_profile)
        if isinstance(raw_capability_profile, dict)
        else CapabilityProfile()
    )
    default_params = _dict_value(config.get("default_params"))
    moe = _dict_or_none(config.get("moe"))
    incompatible_reason = None
    if architecture and architecture not in _SUPPORTED_ARCHITECTURES:
        incompatible_reason = f"????????: {architecture}"
    missing_fields: list[str] = []
    if gguf is None:
        missing_fields.append("gguf_path")
    if not chat_template.strip():
        missing_fields.append("chat_template")
    if n_ctx is None:
        missing_fields.append("n_ctx")
    status = "ready"
    if incompatible_reason is not None:
        status = "incompatible"
    elif missing_fields:
        status = "needs_config"
    return ModelDescriptor(
        model_id=safe_id,
        display_name=display_name,
        gguf_path=str(gguf) if gguf else None,
        source=source,
        status=status,
        backend=backend,
        architecture=architecture,
        n_ctx=n_ctx,
        supports_system_role=supports_system_role,
        add_bos_token=add_bos_token,
        eos_token=eos_token,
        chat_template=chat_template,
        stop_tokens=stop_tokens,
        strip_output_tags=strip_tags,
        capability_profile=capability_profile,
        default_params=default_params,
        moe=moe,
        incompatible_reason=incompatible_reason,
        missing_fields=tuple(missing_fields),
    )


def discover_models(*, data_root_override: Path | None = None) -> list[ModelDescriptor]:
    """????? models ????? YAML??????????"""
    root = models_dir(data_root_override=data_root_override)
    model_ids = {path.stem for path in root.glob("*.gguf")}
    config_root = _model_config_root()
    if config_root.is_dir():
        model_ids.update(path.stem for path in config_root.glob("*.yaml"))
    return [describe_model(model_id, data_root_override=data_root_override) for model_id in sorted(model_ids)]


def resolve_active_model_id(*, data_root_override: Path | None = None) -> str | None:
    """????? `registry.yaml` ?????? ID?"""
    active_id = str(load_registry(data_root_override=data_root_override).get("active") or "").strip()
    return active_id or None


def resolve_default_model_config(*, data_root_override: Path | None = None) -> ModelRuntimeConfig | None:
    """??????????????????"""
    active_id = resolve_active_model_id(data_root_override=data_root_override)
    if not active_id:
        return None
    return runtime_config_from_descriptor(describe_model(active_id, data_root_override=data_root_override))


def resolve_default_gguf_path(*, data_root_override: Path | None = None) -> Path | None:
    """??????? GGUF ???"""
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
    """???CLI `--n-gpu-layers` ? 0 ???????????"""
    if cli_value != 0:
        return cli_value
    env = os.environ.get("OFFLINE_COMPANION_N_GPU_LAYERS")
    if not env:
        return cli_value
    try:
        return int(env)
    except ValueError:
        return cli_value


def _find_gguf_for_model(model_id: str, *, data_root_override: Path | None = None) -> Path | None:
    """?????? ID ????? GGUF ???"""
    root = models_dir(data_root_override=data_root_override)
    exact = root / f"{model_id}.gguf"
    if exact.is_file():
        return exact.resolve()
    registry = load_registry(data_root_override=data_root_override)
    entries = registry.get("entries") or []
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict) or item.get("id") != model_id:
                continue
            file_name = str(item.get("file") or "").strip()
            if not file_name:
                continue
            candidate = root / file_name
            if candidate.is_file():
                return candidate.resolve()
    for candidate in sorted(root.glob("*.gguf")):
        if candidate.stem.lower() == model_id.lower():
            return candidate.resolve()
    return None


def _model_config_root() -> Path:
    """????????????"""
    primary = configs_dir() / "models"
    if primary.is_dir():
        return primary
    return dev_repo_root() / "configs" / "models"


def _tuple_of_str(value: object) -> tuple[str, ...]:
    """?????????????????"""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item))


def _dict_value(value: object) -> dict[str, object]:
    """??????????????"""
    return dict(value) if isinstance(value, dict) else {}


def _dict_or_none(value: object) -> dict[str, object] | None:
    """????????????????"""
    return dict(value) if isinstance(value, dict) else None


def _normalize_optional_str(value: object) -> str | None:
    """??????????????"""
    text = str(value).strip() if value is not None else ""
    return text or None


def _normalize_optional_int(value: object) -> int | None:
    """?????????????"""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_capability_tag(value: object) -> CapabilityTag | None:
    """????????????????????"""
    raw = str(value).strip() if value is not None else ""
    if not raw:
        return None
    try:
        return CapabilityTag(raw)
    except ValueError:
        return None


def _normalize_capability_profile(raw: dict[str, object]) -> CapabilityProfile:
    """摘要：从模型 YAML 映射构造多维能力画像，并为缺失维度提供保守默认值。"""
    return CapabilityProfile(
        instruction_following=float(raw.get("instruction_following", 0.5)),
        roleplay_quality=float(raw.get("roleplay_quality", 0.5)),
        safety_sensitivity=float(raw.get("safety_sensitivity", 0.5)),
        reasoning_ability=float(raw.get("reasoning_ability", 0.5)),
        max_context=int(raw.get("max_context", 4096)),
    )
