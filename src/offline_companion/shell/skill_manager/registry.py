"""registry：扩展 manifest 加载与校验（Schema + 语义化版本 + type 分流）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from offline_companion.shared.errors import SkillManifestError
from offline_companion.shared.runtime_paths import dev_repo_root

from .manifest import SkillEntrypoint, SkillManifest

if TYPE_CHECKING:
    from packaging.version import Version

MANIFEST_TYPE_SKILL = "skill"
MANIFEST_TYPE_PLUGIN = "plugin"
MANIFEST_TYPE_TOOL = "tool"

_KNOWN_PERMISSIONS = frozenset(
    {"cloud_inference", "network_egress", "read_session_context"},
)
_FORBIDDEN_PERMISSIONS = frozenset({"write_memory"})


def _import_jsonschema_validator():
    try:
        from jsonschema import Draft202012Validator
    except ImportError as e:
        raise SkillManifestError(
            "Skill manifest 校验需要可选依赖：pip install -e '.[skill]'"
        ) from e
    return Draft202012Validator


def _import_packaging_version():
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError as e:
        raise SkillManifestError(
            "Skill manifest 校验需要可选依赖：pip install -e '.[skill]'"
        ) from e
    return Version, InvalidVersion


def skill_manifest_schema_path() -> Path:
    """摘要：仓库内扩展 manifest JSON Schema 路径。"""
    return dev_repo_root() / "schemas" / "skill-manifest-v1.json"


def installed_extensions_dir(data_root: Path) -> Path:
    """摘要：已安装扩展根目录 ``{data_root}/extensions/installed``。"""
    path = data_root / "extensions" / "installed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def skill_install_dir(data_root: Path, skill_name: str) -> Path:
    """摘要：单个 Skill 安装目录 ``{data_root}/extensions/installed/<skill-name>/``。

    目录名使用 ``manifest.name``（如 ``novel-writer``），**不是** ``market_id``。
    """
    name = (skill_name or "").strip()
    if not name:
        raise SkillManifestError("skill_name 不能为空")
    return installed_extensions_dir(data_root) / name


def manifest_type_from_dict(data: dict) -> str:
    """摘要：读取 manifest ``type`` 字段（未校验）。"""
    return str(data.get("type") or "").strip()


def parse_market_id(market_id: str) -> tuple[str, str]:
    """摘要：解析 ``{name}@{version}`` 形式的 market_id。"""
    text = (market_id or "").strip()
    if "@" not in text:
        raise SkillManifestError(f"market_id 格式不正确，须为 name@version: {market_id!r}")
    name, version_raw = text.rsplit("@", 1)
    name = name.strip()
    version_raw = version_raw.strip()
    if not name or not version_raw:
        raise SkillManifestError(f"market_id 格式不正确，须为 name@version: {market_id!r}")
    return name, version_raw


def parse_pep440_version(version_raw: str) -> Version:
    """摘要：解析 PEP 440 release 段；MVP 拒绝预发布/本地版本号。"""
    Version, InvalidVersion = _import_packaging_version()
    raw = (version_raw or "").strip()
    if not raw:
        raise SkillManifestError("version 不能为空")
    try:
        parsed = Version(raw)
    except InvalidVersion as e:
        raise SkillManifestError(f"version 无法解析为 PEP 440 release: {raw!r}") from e
    if parsed.pre or parsed.post or parsed.dev or parsed.local:
        raise SkillManifestError(
            f"version 在 MVP 阶段仅接受 release 段（如 1.2.0），拒绝: {raw!r}"
        )
    return parsed


def _load_schema_validator():
    Draft202012Validator = _import_jsonschema_validator()
    path = skill_manifest_schema_path()
    if not path.is_file():
        raise SkillManifestError(f"Skill Schema 不存在: {path}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _format_schema_error(source: str | None, field: str, message: str) -> str:
    prefix = f"文件 {source}: " if source else ""
    return f"{prefix}字段 {field}: {message}"


def validate_manifest_dict(data: dict, *, source: str | None = None) -> SkillManifest:
    """摘要：校验 ``type=skill`` 的 manifest 并返回 ``SkillManifest``（skill_manager 入口）。"""
    if not isinstance(data, dict):
        raise SkillManifestError(_format_schema_error(source, "(root)", "manifest 须为 JSON 对象"))

    validator = _load_schema_validator()
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        field = ".".join(str(p) for p in first.path) or "(root)"
        raise SkillManifestError(_format_schema_error(source, field, first.message))

    mtype = manifest_type_from_dict(data)
    if mtype != MANIFEST_TYPE_SKILL:
        raise SkillManifestError(
            _format_schema_error(
                source,
                "type",
                f"skill_manager 仅接受 type={MANIFEST_TYPE_SKILL!r}，当前为 {mtype!r}",
            )
        )

    perms_raw = data.get("permissions") or []
    if not isinstance(perms_raw, list):
        raise SkillManifestError(_format_schema_error(source, "permissions", "须为数组"))
    for p in perms_raw:
        if p in _FORBIDDEN_PERMISSIONS:
            raise SkillManifestError(
                _format_schema_error(source, "permissions", f"禁止包含 {p!r}")
            )
        if p not in _KNOWN_PERMISSIONS:
            raise SkillManifestError(
                _format_schema_error(source, "permissions", f"含非法值 {p!r}")
            )

    version_raw = str(data.get("version") or "")
    version = parse_pep440_version(version_raw)

    market_id = str(data.get("market_id") or "")
    try:
        mid_name, mid_ver_raw = parse_market_id(market_id)
    except SkillManifestError as e:
        raise SkillManifestError(_format_schema_error(source, "market_id", str(e))) from e

    name = str(data.get("name") or "")
    if mid_name != name:
        raise SkillManifestError(
            _format_schema_error(
                source,
                "market_id",
                f"name 段 {mid_name!r} 与 manifest.name {name!r} 不一致",
            )
        )

    if mid_ver_raw != version_raw:
        raise SkillManifestError(
            _format_schema_error(
                source,
                "market_id",
                f"version 段 {mid_ver_raw!r} 与 manifest.version {version_raw!r} 字面不一致",
            )
        )
    mid_version = parse_pep440_version(mid_ver_raw)
    if mid_version != version:
        raise SkillManifestError(
            _format_schema_error(
                source,
                "market_id",
                f"version 段 {mid_ver_raw!r} 与 manifest.version {version_raw!r} 语义不一致",
            )
        )

    ep = data.get("entrypoint") or {}
    if not isinstance(ep, dict):
        raise SkillManifestError(_format_schema_error(source, "entrypoint", "须为对象"))

    keys_raw = data.get("required_api_keys") or []
    if not isinstance(keys_raw, list):
        raise SkillManifestError(_format_schema_error(source, "required_api_keys", "须为数组"))

    try:
        entrypoint = SkillEntrypoint(
            type=str(ep.get("type") or ""),
            host=str(ep.get("host") or ""),
            port=int(ep.get("port") or 0),
            path=str(ep.get("path") or ""),
        )
    except SkillManifestError as e:
        raise SkillManifestError(_format_schema_error(source, "entrypoint.host", str(e))) from e

    return SkillManifest(
        name=name,
        version=version,
        version_raw=version_raw,
        description=str(data.get("description") or ""),
        market_id=market_id,
        trust=str(data.get("trust") or ""),
        entrypoint=entrypoint,
        permissions=tuple(str(p) for p in perms_raw),
        required_api_keys=tuple(str(k) for k in keys_raw),
        output_mode=str(data.get("output_mode") or ""),
        raw=dict(data),
    )


def load_manifest_file(path: Path) -> SkillManifest:
    """摘要：从 ``manifest.json`` 文件加载并校验（仅 ``type=skill``）。"""
    if not path.is_file():
        raise SkillManifestError(f"manifest 文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SkillManifestError(f"manifest JSON 非法: {path}") from e
    return validate_manifest_dict(data, source=str(path))


def load_installed_manifests(data_root: Path) -> list[SkillManifest]:
    """摘要：扫描 ``extensions/installed/``，仅加载 ``type=skill`` 的 manifest。"""
    root = installed_extensions_dir(data_root)
    if not root.is_dir():
        return []
    manifests: list[SkillManifest] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if manifest_type_from_dict(data) != MANIFEST_TYPE_SKILL:
            continue
        manifests.append(validate_manifest_dict(data, source=str(manifest_path)))
    return manifests


def compare_versions(left: Version, right: Version) -> int:
    """摘要：比较两个已解析版本；禁止对字符串直接比较。"""
    if left < right:
        return -1
    if left > right:
        return 1
    return 0
