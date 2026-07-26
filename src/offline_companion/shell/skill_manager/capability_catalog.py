"""摘要：从 Skill manifest 提取 A 层能力关键词目录，供 CI prompt 解耦扫描复用。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from offline_companion.shell.skill_manager.manifest import SkillManifest
from offline_companion.shell.skill_manager.registry import load_installed_manifests

_ENTRYPOINT_PATH_SEGMENTS = ("path", "entrypoint_path")
_PERMISSION_ALIASES = {
    "network_egress": ("network_egress", "network_post"),
    "read_session_context": ("read_session_context",),
    "cloud_inference": ("cloud_inference",),
}


@dataclass(frozen=True)
class CapabilityKeyword:
    """摘要：单个禁止关键词及其来源描述。"""

    value: str
    source: str


def build_capability_keywords(data_root: Path) -> list[CapabilityKeyword]:
    """摘要：从已安装 Skill manifest 自动生成禁止关键词集合。"""
    keywords: dict[str, CapabilityKeyword] = {}
    for manifest in load_installed_manifests(data_root):
        for keyword in keywords_from_manifest(manifest):
            if keyword.value not in keywords:
                keywords[keyword.value] = keyword
    return list(keywords.values())


def keywords_from_manifest(manifest: SkillManifest) -> list[CapabilityKeyword]:
    """摘要：从单个 Skill manifest 提取名称、入口、权限和 API 字段关键词。"""
    keywords: dict[str, CapabilityKeyword] = {}
    _add_keyword(keywords, manifest.name, f"{manifest.name}:name")
    _add_keyword(keywords, manifest.market_id, f"{manifest.name}:market_id")
    for api_key in manifest.required_api_keys:
        _add_keyword(keywords, api_key, f"{manifest.name}:required_api_keys")
        _add_keyword(keywords, api_key.upper(), f"{manifest.name}:required_api_keys")
    for permission in manifest.permissions:
        aliases = _PERMISSION_ALIASES.get(permission, (permission,))
        for alias in aliases:
            _add_keyword(keywords, alias, f"{manifest.name}:permissions")
    raw_entrypoint = manifest.raw.get("entrypoint")
    if isinstance(raw_entrypoint, dict):
        for field_name in _ENTRYPOINT_PATH_SEGMENTS:
            raw_value = raw_entrypoint.get(field_name)
            if isinstance(raw_value, str):
                _add_entrypoint_keywords(keywords, raw_value, manifest.name)
    return list(keywords.values())


def _add_entrypoint_keywords(
    keywords: dict[str, CapabilityKeyword],
    raw_value: str,
    manifest_name: str,
) -> None:
    text = (raw_value or "").strip()
    if not text:
        return
    _add_keyword(keywords, text, f"{manifest_name}:entrypoint")
    normalized = text.strip("/").replace("\\", "/")
    if not normalized:
        return
    for segment in normalized.split("/"):
        segment = segment.strip()
        if not segment:
            continue
        _add_keyword(keywords, segment, f"{manifest_name}:entrypoint")
        stem = Path(segment).stem.strip()
        if stem and stem != segment:
            _add_keyword(keywords, stem, f"{manifest_name}:entrypoint")


def _add_keyword(
    keywords: dict[str, CapabilityKeyword],
    value: str,
    source: str,
) -> None:
    text = (value or "").strip()
    if not text:
        return
    keywords.setdefault(text, CapabilityKeyword(value=text, source=source))
