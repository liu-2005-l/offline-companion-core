"""摘要：本地扩展安装与卸载编排。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from offline_companion.shared.errors import (
    SkillInvocationError,
    SkillManifestError,
)
from offline_companion.storage.extension_repo import delete_extension_status

from .registry import installed_extensions_dir, load_manifest_file, skill_install_dir
from .supply_chain import verify_supply_chain


class ExtensionAlreadyInstalledError(RuntimeError):
    """摘要：扩展目标目录已存在。"""


class ExtensionNotInstalledError(KeyError):
    """摘要：扩展不存在，无法卸载。"""


def install_extension(data_root: Path, db_path: Path, source_path: Path) -> dict[str, Any]:
    """摘要：从本地目录安装 skill 扩展。

    参数：
        data_root: 应用数据根目录。
        db_path: companion SQLite 数据库路径，用于清理状态残留。
        source_path: 用户选择的扩展源目录。

    返回值：
        已安装扩展的基础信息。

    Raises:
        FileNotFoundError: 源目录不存在。
        ExtensionAlreadyInstalledError: 同名扩展已安装。
        SkillManifestError: manifest 不合法。
        SkillSupplyChainError: 供应链校验失败。
    """
    source = source_path.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(str(source_path))
    manifest = load_manifest_file(source / "manifest.json")
    target = skill_install_dir(data_root, manifest.name)
    if target.exists():
        raise ExtensionAlreadyInstalledError(manifest.name)
    try:
        shutil.copytree(source, target)
        verify_supply_chain(manifest, target)
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise
    delete_extension_status(db_path, manifest.name)
    return {
        "ok": True,
        "id": manifest.name,
        "name": manifest.name,
        "type": "skill",
        "version": manifest.version_raw,
        "description": manifest.description,
    }


def uninstall_extension(data_root: Path, db_path: Path, extension_id: str) -> dict[str, Any]:
    """摘要：卸载已安装扩展并清理启用状态。

    参数：
        data_root: 应用数据根目录。
        db_path: companion SQLite 数据库路径。
        extension_id: 扩展 ID，即 manifest.name。

    返回值：
        卸载结果。

    Raises:
        ExtensionNotInstalledError: 扩展不存在。
        SkillInvocationError: 扩展仍在运行时的保护性错误。
    """
    ext_id = (extension_id or "").strip()
    if not ext_id:
        raise ExtensionNotInstalledError(extension_id)
    target = skill_install_dir(data_root, ext_id)
    root = installed_extensions_dir(data_root).resolve()
    resolved = target.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SkillManifestError("extension_id 越界") from exc
    if not target.exists():
        raise ExtensionNotInstalledError(ext_id)
    if _is_running_marker_present(target):
        raise SkillInvocationError(f"extension {ext_id!r} is running")
    shutil.rmtree(target)
    delete_extension_status(db_path, ext_id)
    return {"ok": True, "deleted": ext_id}


def _is_running_marker_present(target: Path) -> bool:
    return (target / ".running").exists()
