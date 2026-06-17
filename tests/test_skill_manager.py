"""Skill manager：manifest registry 与 policy（Sprint 7.1 · 11 项核对清单）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from packaging.version import Version

from offline_companion.shared.errors import SkillManifestError, SkillPolicyDenied
from offline_companion.shared.types import PrivacyMode
from offline_companion.shell.skill_manager import (
    check_read_context,
    compare_versions,
    evaluate_skill_policy,
    load_installed_manifests,
    load_manifest_file,
    parse_market_id,
    require_skill_allowed,
    skill_install_dir,
    validate_manifest_dict,
)
from offline_companion.shell.skill_manager.manifest import SkillEntrypoint

_SKILLS = Path(__file__).resolve().parents[1] / "fixtures" / "skills"
_VALID = _SKILLS / "novel-writer" / "manifest.json"


def _valid_dict() -> dict:
    return json.loads(_VALID.read_text(encoding="utf-8"))


def test_01_valid_manifest_loads_dto() -> None:
    manifest = load_manifest_file(_VALID)
    assert manifest.name == "novel-writer"
    assert isinstance(manifest.version, Version)
    assert manifest.version == Version("1.2.0")
    assert manifest.entrypoint.host == "127.0.0.1"
    assert skill_install_dir(Path("/tmp/x"), "novel-writer") == Path(
        "/tmp/x/extensions/installed/novel-writer"
    )


def test_02_host_not_localhost_rejected() -> None:
    with pytest.raises(SkillManifestError):
        load_manifest_file(_SKILLS / "invalid-bad-host" / "manifest.json")


def test_03_invalid_permissions_rejected() -> None:
    with pytest.raises(SkillManifestError):
        load_manifest_file(_SKILLS / "invalid-permissions" / "manifest.json")


def test_04_unparseable_version_rejected() -> None:
    with pytest.raises(SkillManifestError, match="PEP 440"):
        load_manifest_file(_SKILLS / "invalid-version" / "manifest.json")


def test_05_malformed_market_id_rejected() -> None:
    with pytest.raises(SkillManifestError, match="格式不正确"):
        parse_market_id("no-at-sign")


def test_06_market_id_name_mismatch_rejected() -> None:
    with pytest.raises(SkillManifestError, match="不一致"):
        load_manifest_file(_SKILLS / "invalid-market-id" / "manifest.json")


def test_07_market_id_version_literal_mismatch_1_2_0_vs_1_2_00() -> None:
    data = _valid_dict()
    data["version"] = "1.2.0"
    data["market_id"] = "novel-writer@1.2.00"
    with pytest.raises(SkillManifestError, match="字面不一致"):
        validate_manifest_dict(data, source="test.json")


def test_08_version_object_compare_1_10_gt_1_2() -> None:
    assert compare_versions(Version("1.10.0"), Version("1.2.0")) == 1
    assert Version("1.10.0") > Version("1.2.0")


def test_09_network_egress_local_only_denied() -> None:
    data = _valid_dict()
    data["permissions"] = ["network_egress"]
    data["market_id"] = "novel-writer@1.2.0"
    manifest = validate_manifest_dict(data)
    result = evaluate_skill_policy(manifest, privacy_mode=PrivacyMode.LOCAL_ONLY)
    assert not result.allowed
    assert not result.requires_consent
    assert result.reason == "当前隐私模式下不可用"


def test_10_cloud_inference_local_only_denied() -> None:
    manifest = load_manifest_file(_VALID)
    result = evaluate_skill_policy(manifest, privacy_mode=PrivacyMode.LOCAL_ONLY)
    assert not result.allowed
    with pytest.raises(SkillPolicyDenied, match="当前隐私模式下不可用"):
        require_skill_allowed(manifest, privacy_mode=PrivacyMode.LOCAL_ONLY)


def test_11_empty_installed_dir_returns_empty_list(tmp_path) -> None:
    assert load_installed_manifests(tmp_path) == []
    # installed_extensions_dir 已在首次调用时创建；空目录仍应返回空列表
    assert load_installed_manifests(tmp_path) == []


def test_entrypoint_dto_rejects_host_at_construction() -> None:
    with pytest.raises(SkillManifestError, match="127.0.0.1"):
        SkillEntrypoint(type="local_api", host="10.0.0.1", port=1, path="/x")


def test_check_read_context_mvp_always_false() -> None:
    manifest = load_manifest_file(_VALID)
    assert check_read_context(manifest, PrivacyMode.ASK_BEFORE_CLOUD) is False


def test_schema_error_includes_file_and_field() -> None:
    with pytest.raises(SkillManifestError, match=r"文件 .*字段 permissions"):
        load_manifest_file(_SKILLS / "invalid-permissions" / "manifest.json")


def test_12_missing_type_rejected() -> None:
    data = _valid_dict()
    del data["type"]
    with pytest.raises(SkillManifestError, match="type"):
        validate_manifest_dict(data, source="test.json")


def test_13_plugin_type_rejected_by_skill_manager() -> None:
    data = {
        "type": "plugin",
        "name": "voice-input",
        "version": "1.0.0",
        "description": "语音输入",
        "market_id": "voice-input@1.0.0",
        "trust": "user_installed",
        "ui_contributions": {},
    }
    with pytest.raises(SkillManifestError, match="skill_manager 仅接受"):
        validate_manifest_dict(data, source="test.json")


def test_14_optional_csp_and_error_codes_accepted() -> None:
    data = _valid_dict()
    data["content_security_policy"] = {"allowed_domains": [], "allow_local_fetch": True}
    data["error_codes"] = {"E001": "示例占位"}
    manifest = validate_manifest_dict(data)
    assert manifest.raw["error_codes"]["E001"] == "示例占位"


def test_15_load_installed_skips_non_skill_manifests(tmp_path) -> None:
    root = tmp_path / "extensions" / "installed"
    skill_dir = root / "novel-writer"
    plugin_dir = root / "voice-input"
    skill_dir.mkdir(parents=True)
    plugin_dir.mkdir(parents=True)
    skill_dir.joinpath("manifest.json").write_text(
        json.dumps(_valid_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    plugin_dir.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "type": "plugin",
                "name": "voice-input",
                "version": "1.0.0",
                "description": "语音",
                "market_id": "voice-input@1.0.0",
                "trust": "user_installed",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = load_installed_manifests(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].name == "novel-writer"
