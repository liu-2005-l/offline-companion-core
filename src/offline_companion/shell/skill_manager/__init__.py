"""skill_manager：A2 Skill 外骨骼（registry / policy；安装与调用见 Sprint 7.3+）。"""

from offline_companion.shell.skill_manager.manifest import SkillEntrypoint, SkillManifest
from offline_companion.shell.skill_manager.policy import (
    SkillPolicyResult,
    check_read_context,
    evaluate_skill_policy,
    require_skill_allowed,
)
from offline_companion.shell.skill_manager.registry import (
    MANIFEST_TYPE_PLUGIN,
    MANIFEST_TYPE_SKILL,
    MANIFEST_TYPE_TOOL,
    compare_versions,
    installed_extensions_dir,
    load_installed_manifests,
    load_manifest_file,
    manifest_type_from_dict,
    parse_market_id,
    parse_pep440_version,
    skill_install_dir,
    validate_manifest_dict,
)

__all__ = [
    "SkillEntrypoint",
    "SkillManifest",
    "SkillPolicyResult",
    "check_read_context",
    "compare_versions",
    "evaluate_skill_policy",
    "MANIFEST_TYPE_PLUGIN",
    "MANIFEST_TYPE_SKILL",
    "MANIFEST_TYPE_TOOL",
    "installed_extensions_dir",
    "manifest_type_from_dict",
    "load_installed_manifests",
    "load_manifest_file",
    "parse_market_id",
    "parse_pep440_version",
    "require_skill_allowed",
    "skill_install_dir",
    "validate_manifest_dict",
]
