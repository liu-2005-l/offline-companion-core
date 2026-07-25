"""摘要：Skill 供应链安全校验与 SBOM 生成。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from offline_companion.shared.errors import (
    SkillBuiltinHashMismatchError,
    SkillHashMissingError,
    SkillTrustAnchorMissingError,
)

if TYPE_CHECKING:
    from .manifest import SkillManifest

_SBOM_FILENAME = "sbom.json"
_BUNDLED_HASH_FILENAME = "builtin_hashes.json"
_TRUST_ANCHOR_DIRNAME = "builtin_skill_hashes"


@dataclass(frozen=True)
class RequirementRecord:
    """摘要：单条 requirements 锁定记录。"""

    package: str
    raw_line: str
    hashes: tuple[str, ...]


def sbom_path(install_dir: Path) -> Path:
    """摘要：返回 Skill SBOM 路径。"""
    return install_dir / _SBOM_FILENAME


def bundled_hash_manifest_path(install_dir: Path) -> Path:
    """摘要：返回 Skill 包内自带的内置哈希清单路径。"""
    return install_dir / _BUNDLED_HASH_FILENAME


def host_trust_anchor_path(install_dir: Path, skill_name: str) -> Path:
    """摘要：返回宿主侧内置 Skill 信任锚路径。"""
    data_root = _data_root_from_install_dir(install_dir)
    directory = data_root / "security" / _TRUST_ANCHOR_DIRNAME
    return directory / f"{skill_name}.json"


def verify_supply_chain(manifest: SkillManifest, install_dir: Path) -> Path:
    """摘要：执行 Skill 启动前供应链校验并刷新 SBOM。"""
    install_root = install_dir.resolve()
    requirements = install_root / "requirements.txt"
    if requirements.is_file():
        verify_requirements_hashes(requirements)
    if manifest.trust == "bundled":
        verify_bundled_skill_integrity(install_root, manifest.name)
    return write_sbom(manifest, install_root)


def verify_requirements_hashes(requirements_path: Path) -> list[RequirementRecord]:
    """摘要：校验 requirements.txt 每条依赖都显式锁定 sha256 哈希。"""
    records: list[RequirementRecord] = []
    for idx, line in enumerate(requirements_path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith(("-", "--")):
            continue
        hashes = tuple(_extract_hashes(raw))
        if not hashes:
            raise SkillHashMissingError(f"requirements.txt 第 {idx} 行缺少 --hash=sha256:... 锁定")
        if "==" not in raw:
            raise SkillHashMissingError(f"requirements.txt 第 {idx} 行未锁定精确版本")
        package = raw.split("==", 1)[0].strip()
        records.append(RequirementRecord(package=package, raw_line=raw, hashes=hashes))
    return records


def verify_bundled_skill_integrity(install_dir: Path, skill_name: str) -> dict[str, str]:
    """摘要：校验内置 Skill 文件哈希。

    说明：
        第一阶段仅在 Skill 启动前校验，不做运行时重校验；运行后热替换仍是已知缺口。
    """
    manifest_path = host_trust_anchor_path(install_dir, skill_name)
    if not manifest_path.is_file():
        raise SkillTrustAnchorMissingError("内置 Skill 宿主侧信任锚缺失，请先完成安装登记流程")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkillBuiltinHashMismatchError("内置 Skill 文件完整性校验失败，请联系开发者") from exc
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise SkillBuiltinHashMismatchError("内置 Skill 文件完整性校验失败，请联系开发者")
    checked: dict[str, str] = {}
    for relative_path, expected_hash in files.items():
        rel = str(relative_path).replace("\\", "/").strip()
        if not rel:
            raise SkillBuiltinHashMismatchError("内置 Skill 文件完整性校验失败，请联系开发者")
        file_path = (install_dir / rel).resolve()
        if not _is_within_directory(file_path, install_dir.resolve()):
            raise SkillBuiltinHashMismatchError("内置 Skill 文件完整性校验失败，请联系开发者")
        if not file_path.is_file():
            raise SkillBuiltinHashMismatchError("内置 Skill 文件完整性校验失败，请联系开发者")
        actual_hash = sha256_file(file_path)
        if actual_hash != str(expected_hash):
            raise SkillBuiltinHashMismatchError("内置 Skill 文件完整性校验失败，请联系开发者")
        checked[rel] = actual_hash
    return checked


def write_sbom(manifest: SkillManifest, install_dir: Path) -> Path:
    """摘要：生成 CycloneDX 1.5 最小子集 SBOM。"""
    requirements_path = install_dir / "requirements.txt"
    dependency_records = verify_requirements_hashes(requirements_path) if requirements_path.is_file() else []
    components: list[dict[str, Any]] = []
    for path in sorted(install_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(install_dir).as_posix()
        if rel == _SBOM_FILENAME:
            continue
        components.append(
            {
                "type": "file",
                "name": rel,
                "version": "0",
                "scope": "required",
                "hashes": [{"alg": "SHA-256", "content": sha256_file(path)}],
                "properties": [{"name": "offline_companion:size", "value": str(path.stat().st_size)}],
            }
        )
    for record in dependency_records:
        version = record.raw_line.split("==", 1)[1].split()[0].strip()
        components.append(
            {
                "type": "library",
                "name": record.package,
                "version": version,
                "scope": "required",
                "hashes": [{"alg": "SHA-256", "content": value} for value in record.hashes],
            }
        )
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": manifest.name,
                "version": manifest.version_raw,
            },
            "properties": [
                {"name": "offline_companion:trust", "value": manifest.trust},
                {"name": "offline_companion:market_id", "value": manifest.market_id},
                {"name": "offline_companion:permissions", "value": ",".join(manifest.permissions)},
            ],
        },
        "components": components,
    }
    output = sbom_path(install_dir)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def register_bundled_trust_anchor(install_dir: Path, skill_name: str) -> Path:
    """摘要：将 Skill 包内哈希清单登记到宿主侧信任锚目录。

    说明：
        调用方必须是可信 installer 或等效发布流程；本函数只负责登记，不负责来源签名校验。
    """
    source = bundled_hash_manifest_path(install_dir)
    if not source.is_file():
        raise SkillTrustAnchorMissingError("内置 Skill 宿主侧信任锚缺失，请先完成安装登记流程")
    payload = json.loads(source.read_text(encoding="utf-8"))
    target = host_trust_anchor_path(install_dir, skill_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def audit_supply_chain_failure(exc: BaseException, *, skill_name: str, path: str | None = None) -> dict[str, Any]:
    """摘要：返回供应链失败的审计字段。"""
    error_code = getattr(exc, "error_code", None)
    return {
        "skill_id": skill_name,
        "path": path,
        "error_code": error_code.code if error_code is not None else None,
        "error_type": exc.__class__.__name__,
        "reason": str(exc),
    }


def sha256_file(path: Path) -> str:
    """摘要：计算文件 sha256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_hashes(line: str) -> list[str]:
    hashes: list[str] = []
    for part in line.split():
        if part.startswith("--hash=sha256:"):
            hashes.append(part[len("--hash=sha256:"):].strip())
    return hashes


def _is_within_directory(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _data_root_from_install_dir(install_dir: Path) -> Path:
    resolved = install_dir.resolve()
    parent = resolved.parent
    if parent.name == "installed" and parent.parent.name == "extensions":
        return parent.parent.parent
    raise SkillTrustAnchorMissingError(f"无法从安装路径推断 data_root: {install_dir}")
