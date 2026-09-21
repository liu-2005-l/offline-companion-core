"""摘要：人格约束语料的共享纯 lint 规则，不承担发布哈希校验。"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_DISPLAY_NAME = "小岚"
ABSOLUTE_PROMISE_PATTERN = re.compile(r"(?:保证|肯定|绝对|百分之百|永远|一定会|不会再|随时都)")
MECHANISM_LEAK_PATTERN = re.compile(
    r"(?:OCEAN|L[1-4]|manifest|sha-?256|schema|DTO|backend|system\s*prompt|"
    r"系统提示词|模型参数|采样参数|内部机制|哈希|快照|档位映射)",
    flags=re.IGNORECASE,
)


def scan_forbidden(text: str, lexicon: Mapping[str, Any]) -> list[str]:
    """摘要：返回命中的禁用语义族名称。"""
    compact_text = _compact(text)
    families = lexicon.get("forbidden_semantic_families")
    if not isinstance(families, Mapping):
        return ["invalid_forbidden_semantic_families"]
    hits: list[str] = []
    for family_name, family in families.items():
        if not isinstance(family, Mapping):
            hits.append(str(family_name))
            continue
        variants = family.get("variants")
        if not isinstance(variants, Sequence) or isinstance(variants, (str, bytes)):
            hits.append(str(family_name))
            continue
        if any(_compact(str(variant)) in compact_text for variant in variants):
            hits.append(str(family_name))
    return hits


def scan_l4(
    text: str,
    patterns: Mapping[str, Any],
    *,
    display_name_present: bool | None = None,
) -> dict[str, Any]:
    """摘要：按 P1 模式语言返回首个命中分区与模式族。"""
    if display_name_present is None:
        display_name_present = _compact(DEFAULT_DISPLAY_NAME) in _compact(text)
    zones = patterns.get("zones")
    if not isinstance(zones, Mapping):
        return {"hit": True, "zone": "invalid", "family": "zones"}
    for zone_name, zone in zones.items():
        if not isinstance(zone, Mapping) or not isinstance(zone.get("families"), Mapping):
            return {"hit": True, "zone": str(zone_name), "family": "invalid"}
        for family_name, family in zone["families"].items():
            if not isinstance(family, Mapping):
                return {"hit": True, "zone": str(zone_name), "family": str(family_name)}
            if not re.search(str(family.get("pattern") or r"(?!)"), text, flags=re.IGNORECASE):
                continue
            exclude_pattern = family.get("exclude_pattern")
            if exclude_pattern and re.search(str(exclude_pattern), text, flags=re.IGNORECASE):
                continue
            if family.get("requires_display_name_absent") and display_name_present:
                continue
            return {"hit": True, "zone": str(zone_name), "family": str(family_name)}
    return {"hit": False, "zone": None, "family": None}


def detect_copy(reply: str, examples: Sequence[str], output_tokens: int) -> dict[str, Any]:
    """摘要：按短前缀与长连续子串双规则检测示例复制。"""
    normalized_reply = _copy_normalize(reply)
    best_chars = 0
    for example in examples:
        normalized_example = _copy_normalize(example)
        if (
            output_tokens <= 16
            and _han_count(normalized_reply) >= 4
            and normalized_example.startswith(normalized_reply)
        ):
            return {
                "hit": True,
                "kind": "short_exact_prefix",
                "matched_chars": len(normalized_reply),
            }
        match = difflib.SequenceMatcher(
            None,
            normalized_reply,
            normalized_example,
            autojunk=False,
        ).find_longest_match()
        best_chars = max(best_chars, match.size)
    if output_tokens < 40 and best_chars >= 10:
        return {"hit": True, "kind": "long_contiguous_substring", "matched_chars": best_chars}
    return {"hit": False, "kind": None, "matched_chars": best_chars}


def scan_absolute_promises(text: str) -> tuple[str, ...]:
    """摘要：返回无证据绝对承诺词的确定性命中序列。"""
    return tuple(match.group(0) for match in ABSOLUTE_PROMISE_PATTERN.finditer(text))


def scan_mechanism_leaks(text: str) -> tuple[str, ...]:
    """摘要：返回面向用户语料中的内部机制泄漏词。"""
    return tuple(match.group(0) for match in MECHANISM_LEAK_PATTERN.finditer(text))


def scan_literal_display_names(text: str, forbidden_names: Sequence[str]) -> tuple[str, ...]:
    """摘要：返回结构语料中被禁止写死的具体自称。"""
    return tuple(str(name) for name in forbidden_names if str(name) and str(name) in text)


def disagreement_share(scenarios: Sequence[str]) -> float:
    """摘要：计算组合引用中 disagreement 场景的占比。"""
    return scenarios.count("disagreement") / len(scenarios) if scenarios else 0.0


def manifest_reference_issues(manifest: Mapping[str, Any], root: Path) -> tuple[str, ...]:
    """摘要：检查单入口 schema、相对引用、物理存在与哈希键集合一致性。"""
    issues: list[str] = []
    if manifest.get("schema_version") != 1:
        issues.append("manifest_schema_invalid")
    sources = manifest.get("sources")
    metadata = manifest.get("manifest")
    hashes = metadata.get("source_sha256") if isinstance(metadata, Mapping) else None
    if not isinstance(sources, Mapping):
        return (*issues, "manifest_sources_invalid")
    if not isinstance(hashes, Mapping):
        issues.append("manifest_source_hashes_invalid")
        hashes = {}
    if set(sources) != set(hashes):
        issues.append("manifest_source_hash_keys_mismatch")
    seen: set[PurePosixPath] = set()
    for name, raw_path in sources.items():
        if not isinstance(raw_path, str) or not raw_path:
            issues.append(f"source_path_invalid:{name}")
            continue
        path = PurePosixPath(raw_path)
        if path.is_absolute() or ".." in path.parts or "\\" in raw_path:
            issues.append(f"source_path_outside_root:{name}")
            continue
        if path in seen:
            issues.append(f"source_path_duplicate:{name}")
        seen.add(path)
        if not (root / Path(*path.parts)).is_file():
            issues.append(f"source_missing:{name}")
    return tuple(issues)


def assistant_texts(value: object) -> tuple[str, ...]:
    """摘要：按 YAML 顺序递归提取全部 assistant 文本。"""
    result: list[str] = []
    if isinstance(value, Mapping):
        assistant = value.get("assistant")
        if isinstance(assistant, str):
            result.append(assistant)
        for nested in value.values():
            result.extend(assistant_texts(nested))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            result.extend(assistant_texts(nested))
    return tuple(result)


def _compact(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).lower().split())


def _copy_normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).strip().split())


def _han_count(text: str) -> int:
    return sum("\u4e00" <= char <= "\u9fff" for char in text)
