"""摘要：按完整根与发布哈希加载人格约束冻结资产。"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal

import yaml

from offline_companion.shared.runtime_paths import bundled_configs_dir, data_root, dev_repo_root

PERSONA_CONSTRAINT_MANIFEST_SHA256 = "1c674a41378f3557fcd728f42e1945ecdac8700c3e4b6b723d0e5bce57f815a7"
PERSONA_CONSTRAINT_MANIFEST_RELATIVE_PATH = Path("configs") / "persona_constraint_corpus.yaml"
PERSONA_CONSTRAINT_ASSET_ROOT_ENV = "OFFLINE_COMPANION_PERSONA_ASSET_ROOT"
OCEAN_DIMENSION_ORDER = ("O", "C", "E", "A", "N")
REPLY_COPY_SWITCH_CONFIRMATION = "switch_confirmation"
REPLY_COPY_MEMORY_SAVED_CONFIRMATION = "memory_saved_confirmation"
REPLY_COPY_CONSTRAINT_CONFIG_FALLBACK = "constraint_config_fallback"
ReplyCopyKind = Literal[
    "switch_confirmation",
    "memory_saved_confirmation",
    "constraint_config_fallback",
]

_REQUIRED_SOURCES = (
    "mappings",
    "coverage_contract",
    "dimension_corpus",
    "structural_corpus",
    "persona_compositions",
    "reply_copy",
    "downgrade",
    "l4_patterns",
)
_REPLY_COPY_KINDS = (
    REPLY_COPY_SWITCH_CONFIRMATION,
    REPLY_COPY_MEMORY_SAVED_CONFIRMATION,
    REPLY_COPY_CONSTRAINT_CONFIG_FALLBACK,
)
_PRESET_VALUES = frozenset({17, 50, 83})
_STABLE_ID_PATTERN = re.compile(r"builtin_[a-z0-9_]+\Z")


class PersonaConstraintConfigError(RuntimeError):
    """摘要：人格约束冻结资产缺失、越界或完整性校验失败。"""


@dataclass(frozen=True)
class BuiltinPersonaPreset:
    """摘要：由冻结组合与 A2 存储投影共同构成的内置人格预设。"""

    persona_id: str
    name: str
    persona_type: str
    avatar: str
    description: str
    base_system_prompt: str
    ocean: tuple[int, int, int, int, int]
    levels: tuple[str, str, str, str, str]
    derived_traits: tuple[str, ...]

    def storage_payload(self) -> dict[str, Any]:
        """摘要：生成供存储门面消费的确定性 seed payload。

        返回值：
            不含数据库时间戳与 active 状态的内置人格字段。
        """
        return {
            "id": self.persona_id,
            "name": self.name,
            "avatar": self.avatar,
            "desc": self.description,
            "ocean": list(self.ocean),
            "traits": [],
            "derived_traits": list(self.derived_traits),
            "derived_levels": dict(zip(OCEAN_DIMENSION_ORDER, self.levels, strict=True)),
            "anchor": self.base_system_prompt,
            "system_prompt": self.base_system_prompt,
            "builtin": True,
            "validation_status": "validated_anchor",
            "validated_anchor_id": self.persona_id,
        }


@dataclass(frozen=True)
class PersonaReplyCopy:
    """摘要：一个已验证内置人格的三类确定性回复文案。"""

    switch_confirmation: str
    memory_saved_confirmation: str
    constraint_config_fallback: str

    def get(self, kind: ReplyCopyKind) -> str:
        """摘要：按冻结类型返回确定性文案。

        参数：
            kind: 三类白名单文案之一。
        返回值：
            对应人格的冻结文案。
        """
        return str(getattr(self, kind))


@dataclass(frozen=True)
class PersonaConstraintAssets:
    """摘要：已从同一完整根加载并通过哈希校验的人格约束资产。"""

    root: Path
    manifest_path: Path
    manifest_sha256: str
    manifest: Mapping[str, Any]
    source_paths: Mapping[str, Path]
    source_payloads: Mapping[str, Mapping[str, Any]]
    builtin_presets: tuple[BuiltinPersonaPreset, ...]
    reply_copy: Mapping[str, PersonaReplyCopy]

    def deterministic_reply(self, persona_id: str, kind: ReplyCopyKind) -> str | None:
        """摘要：仅为五个已验证内置人格查找确定性文案。

        参数：
            persona_id: 稳定人格 ID。
            kind: 三类白名单文案之一。
        返回值：
            命中时返回冻结文案，非内置人格返回 ``None``。
        """
        item = self.reply_copy.get(str(persona_id))
        return item.get(kind) if item is not None else None


def load_persona_constraint_assets(*, root_override: Path | None = None) -> PersonaConstraintAssets:
    """摘要：按优先级选择首个完整且哈希一致的人格约束资产根。

    参数：
        root_override: 测试或开发显式候选根；提供后只校验该根并在失败时直接报错。
    返回值：
        通过发布 manifest 与八份源文件逐项校验的资产集合。
    Raises:
        PersonaConstraintConfigError: 无候选根通过完整性或结构校验。
    """
    candidates, strict = _candidate_roots(root_override)
    failures: list[str] = []
    for candidate in candidates:
        try:
            return _load_complete_root(candidate)
        except PersonaConstraintConfigError as exc:
            if strict:
                raise
            failures.append(f"{candidate}: {exc}")
    detail = "; ".join(failures) if failures else "no_candidate_root"
    raise PersonaConstraintConfigError(f"persona_constraint_assets_unavailable: {detail}")


def _candidate_roots(root_override: Path | None) -> tuple[tuple[Path, ...], bool]:
    if root_override is not None:
        return ((_normalize_root(root_override),), True)
    env_override = os.environ.get(PERSONA_CONSTRAINT_ASSET_ROOT_ENV)
    if env_override:
        return ((_normalize_root(Path(env_override).expanduser()),), True)

    roots: list[Path] = [data_root()]
    bundled = bundled_configs_dir()
    if bundled is not None:
        roots.append(bundled.parent)
    roots.append(dev_repo_root())

    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        normalized = _normalize_root(root)
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return tuple(unique), False


def _normalize_root(root: Path) -> Path:
    resolved = root.resolve()
    if resolved.name.casefold() == "configs" and (resolved / "persona_constraint_corpus.yaml").is_file():
        return resolved.parent
    return resolved


def _load_complete_root(root: Path) -> PersonaConstraintAssets:
    manifest_path = root / PERSONA_CONSTRAINT_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        raise PersonaConstraintConfigError("manifest_missing")
    manifest_hash = _sha256(manifest_path)
    if manifest_hash != PERSONA_CONSTRAINT_MANIFEST_SHA256:
        raise PersonaConstraintConfigError("manifest_hash_mismatch")
    manifest = _load_yaml_mapping(manifest_path, "manifest_invalid")
    if int(manifest.get("schema_version", -1)) != 1:
        raise PersonaConstraintConfigError("manifest_schema_unsupported")

    sources = _mapping(manifest.get("sources"), "manifest_sources_invalid")
    manifest_meta = _mapping(manifest.get("manifest"), "manifest_metadata_invalid")
    if int(manifest_meta.get("schema_version", -1)) != 1:
        raise PersonaConstraintConfigError("manifest_metadata_schema_unsupported")
    if manifest_meta.get("hash_algorithm") != "sha256":
        raise PersonaConstraintConfigError("manifest_hash_algorithm_unsupported")
    source_hashes = _mapping(manifest_meta.get("source_sha256"), "manifest_source_hashes_invalid")

    source_paths: dict[str, Path] = {}
    source_payloads: dict[str, Mapping[str, Any]] = {}
    for source_name in _REQUIRED_SOURCES:
        raw_path = sources.get(source_name)
        expected_hash = source_hashes.get(source_name)
        if not isinstance(raw_path, str) or not raw_path:
            raise PersonaConstraintConfigError(f"source_path_invalid:{source_name}")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise PersonaConstraintConfigError(f"source_hash_invalid:{source_name}")
        source_path = _safe_source_path(root, raw_path)
        if not source_path.is_file():
            raise PersonaConstraintConfigError(f"source_missing:{source_name}")
        if _sha256(source_path) != expected_hash:
            raise PersonaConstraintConfigError(f"source_hash_mismatch:{source_name}")
        source_payload = _load_yaml_mapping(source_path, f"source_invalid:{source_name}")
        if int(source_payload.get("schema_version", -1)) != 1:
            raise PersonaConstraintConfigError(f"source_schema_unsupported:{source_name}")
        source_paths[source_name] = source_path
        source_payloads[source_name] = source_payload

    presets = _load_builtin_presets(manifest_meta, source_payloads)
    reply_copy = _load_reply_copy(source_payloads["reply_copy"], presets)
    return PersonaConstraintAssets(
        root=root,
        manifest_path=manifest_path,
        manifest_sha256=manifest_hash,
        manifest=MappingProxyType(dict(manifest)),
        source_paths=MappingProxyType(source_paths),
        source_payloads=MappingProxyType(source_payloads),
        builtin_presets=presets,
        reply_copy=reply_copy,
    )


def _load_builtin_presets(
    manifest_meta: Mapping[str, Any],
    source_payloads: Mapping[str, Mapping[str, Any]],
) -> tuple[BuiltinPersonaPreset, ...]:
    builtin = _mapping(manifest_meta.get("builtin_personas"), "builtin_personas_invalid")
    base_prompt = builtin.get("base_system_prompt")
    if not isinstance(base_prompt, str) or not base_prompt.strip():
        raise PersonaConstraintConfigError("builtin_base_prompt_invalid")
    storage_presets = _mapping(builtin.get("presets"), "builtin_presets_invalid")
    compositions = _mapping(
        source_payloads["persona_compositions"].get("personas"),
        "persona_compositions_invalid",
    )
    mapped_traits = _mapping(source_payloads["mappings"].get("traits"), "persona_mappings_invalid")
    if set(storage_presets) != set(compositions):
        raise PersonaConstraintConfigError("builtin_preset_names_mismatch")

    result: list[BuiltinPersonaPreset] = []
    stable_ids: set[str] = set()
    for name, composition_value in compositions.items():
        if not isinstance(name, str) or not name:
            raise PersonaConstraintConfigError("builtin_preset_name_invalid")
        composition = _mapping(composition_value, f"persona_composition_invalid:{name}")
        mapped_trait = _mapping(mapped_traits.get(name), f"persona_mapping_missing:{name}")
        storage = _mapping(storage_presets.get(name), f"builtin_storage_missing:{name}")
        levels = _levels(composition.get("levels"), name)
        if _levels(mapped_trait.get("levels"), name) != levels:
            raise PersonaConstraintConfigError(f"persona_mapping_levels_mismatch:{name}")
        persona_type = composition.get("type")
        if persona_type not in {"style", "behavior"} or mapped_trait.get("type") != persona_type:
            raise PersonaConstraintConfigError(f"persona_type_mismatch:{name}")

        stable_id = storage.get("stable_id")
        avatar = storage.get("avatar")
        description = storage.get("description")
        ocean = storage.get("ocean")
        if not isinstance(stable_id, str) or _STABLE_ID_PATTERN.fullmatch(stable_id) is None:
            raise PersonaConstraintConfigError(f"builtin_stable_id_invalid:{name}")
        if stable_id in stable_ids:
            raise PersonaConstraintConfigError(f"builtin_stable_id_duplicate:{stable_id}")
        if not isinstance(avatar, str) or len(avatar) != 1:
            raise PersonaConstraintConfigError(f"builtin_avatar_invalid:{name}")
        if not isinstance(description, str) or not description.strip():
            raise PersonaConstraintConfigError(f"builtin_description_invalid:{name}")
        if not isinstance(ocean, list) or len(ocean) != len(OCEAN_DIMENSION_ORDER):
            raise PersonaConstraintConfigError(f"builtin_ocean_invalid:{name}")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in ocean):
            raise PersonaConstraintConfigError(f"builtin_ocean_invalid:{name}")
        ocean_tuple = tuple(ocean)
        if any(value not in _PRESET_VALUES for value in ocean_tuple):
            raise PersonaConstraintConfigError(f"builtin_ocean_not_representative:{name}")
        derived_levels = tuple(_preset_level(value) for value in ocean_tuple)
        if derived_levels != levels:
            raise PersonaConstraintConfigError(f"builtin_ocean_levels_mismatch:{name}")

        stable_ids.add(stable_id)
        result.append(
            BuiltinPersonaPreset(
                persona_id=stable_id,
                name=name,
                persona_type=persona_type,
                avatar=avatar,
                description=description,
                base_system_prompt=base_prompt.strip(),
                ocean=ocean_tuple,
                levels=levels,
                derived_traits=(name,),
            )
        )
    return tuple(result)


def _load_reply_copy(
    payload: Mapping[str, Any],
    presets: tuple[BuiltinPersonaPreset, ...],
) -> Mapping[str, PersonaReplyCopy]:
    table = _mapping(payload.get("reply_copy"), "reply_copy_invalid")
    expected_ids = {preset.persona_id for preset in presets}
    if set(table) != expected_ids:
        raise PersonaConstraintConfigError("reply_copy_personas_mismatch")

    result: dict[str, PersonaReplyCopy] = {}
    for persona_id in sorted(expected_ids):
        raw = _mapping(table.get(persona_id), f"reply_copy_persona_invalid:{persona_id}")
        if set(raw) != set(_REPLY_COPY_KINDS):
            raise PersonaConstraintConfigError(f"reply_copy_kinds_mismatch:{persona_id}")
        values: dict[str, str] = {}
        for kind in _REPLY_COPY_KINDS:
            value = raw.get(kind)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise PersonaConstraintConfigError(f"reply_copy_text_invalid:{persona_id}:{kind}")
            values[kind] = value
        result[persona_id] = PersonaReplyCopy(
            switch_confirmation=values[REPLY_COPY_SWITCH_CONFIRMATION],
            memory_saved_confirmation=values[REPLY_COPY_MEMORY_SAVED_CONFIRMATION],
            constraint_config_fallback=values[REPLY_COPY_CONSTRAINT_CONFIG_FALLBACK],
        )
    return MappingProxyType(result)


def _mapping(value: Any, error: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PersonaConstraintConfigError(error)
    return value


def _levels(value: Any, name: str) -> tuple[str, str, str, str, str]:
    mapping = _mapping(value, f"persona_levels_invalid:{name}")
    if set(mapping) != set(OCEAN_DIMENSION_ORDER):
        raise PersonaConstraintConfigError(f"persona_levels_invalid:{name}")
    levels = tuple(mapping[dimension] for dimension in OCEAN_DIMENSION_ORDER)
    if any(level not in {"low", "mid", "high"} for level in levels):
        raise PersonaConstraintConfigError(f"persona_levels_invalid:{name}")
    return levels


def _preset_level(value: int) -> str:
    if value <= 33:
        return "low"
    if value <= 66:
        return "mid"
    return "high"


def _safe_source_path(root: Path, raw_path: str) -> Path:
    posix_path = PurePosixPath(raw_path)
    if posix_path.is_absolute() or ".." in posix_path.parts or "\\" in raw_path:
        raise PersonaConstraintConfigError("source_path_outside_root")
    resolved = (root / Path(*posix_path.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PersonaConstraintConfigError("source_path_outside_root") from exc
    return resolved


def _load_yaml_mapping(path: Path, error: str) -> Mapping[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PersonaConstraintConfigError(error) from exc
    if not isinstance(loaded, dict):
        raise PersonaConstraintConfigError(error)
    return loaded


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PersonaConstraintConfigError("asset_read_failed") from exc
    return digest.hexdigest()
