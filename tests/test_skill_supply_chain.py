"""Skill 供应链安全测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from packaging.version import Version

from offline_companion.shared.errors import SkillInvocationError
from offline_companion.shell.skill_manager import (
    audit_supply_chain_failure,
    bundled_hash_manifest_path,
    host_trust_anchor_path,
    register_bundled_trust_anchor,
    sha256_file,
    verify_bundled_skill_integrity,
    verify_requirements_hashes,
    verify_supply_chain,
)
from offline_companion.shell.skill_manager.manifest import SkillEntrypoint, SkillManifest


def _manifest(*, trust: str = "user_installed") -> SkillManifest:
    return SkillManifest(
        name="demo-skill",
        version=Version("1.0.0"),
        version_raw="1.0.0",
        description="demo",
        market_id="demo-skill@1.0.0",
        trust=trust,
        entrypoint=SkillEntrypoint(
            type="local_api",
            host="127.0.0.1",
            port=0,
            path="/entry.py",
        ),
        permissions=(),
        required_api_keys=(),
        output_mode="block",
        raw={},
    )


def test_verify_requirements_hashes_rejects_missing_hash(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests==2.32.0\n", encoding="utf-8")
    with pytest.raises(SkillInvocationError, match="缺少 --hash=sha256"):
        verify_requirements_hashes(requirements)


def test_verify_requirements_hashes_accepts_locked_line(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests==2.32.0 --hash=sha256:abcdef123456\n", encoding="utf-8")
    records = verify_requirements_hashes(requirements)
    assert len(records) == 1
    assert records[0].package == "requests"


def test_verify_bundled_skill_integrity_rejects_hash_mismatch(tmp_path: Path) -> None:
    install_dir = tmp_path / "extensions" / "installed" / "demo-skill"
    install_dir.mkdir(parents=True, exist_ok=True)
    entry = install_dir / "entry.py"
    entry.write_text("print('demo')\n", encoding="utf-8")
    host_trust_anchor_path(install_dir, "demo-skill").parent.mkdir(parents=True, exist_ok=True)
    host_trust_anchor_path(install_dir, "demo-skill").write_text(
        json.dumps({"files": {"entry.py": "wrong-hash"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(SkillInvocationError, match="完整性校验失败"):
        verify_bundled_skill_integrity(install_dir, "demo-skill")


def test_verify_bundled_skill_integrity_accepts_matching_hash(tmp_path: Path) -> None:
    install_dir = tmp_path / "extensions" / "installed" / "demo-skill"
    install_dir.mkdir(parents=True, exist_ok=True)
    entry = install_dir / "entry.py"
    entry.write_text("print('demo')\n", encoding="utf-8")
    host_trust_anchor_path(install_dir, "demo-skill").parent.mkdir(parents=True, exist_ok=True)
    host_trust_anchor_path(install_dir, "demo-skill").write_text(
        json.dumps({"files": {"entry.py": sha256_file(entry)}}, ensure_ascii=False),
        encoding="utf-8",
    )
    checked = verify_bundled_skill_integrity(install_dir, "demo-skill")
    assert checked["entry.py"] == sha256_file(entry)


def test_verify_supply_chain_generates_sbom_for_user_skill(tmp_path: Path) -> None:
    install_dir = tmp_path / "demo-skill"
    install_dir.mkdir()
    (install_dir / "entry.py").write_text("print('ok')\n", encoding="utf-8")
    (install_dir / "requirements.txt").write_text(
        "requests==2.32.0 --hash=sha256:abcdef123456\n",
        encoding="utf-8",
    )
    sbom = verify_supply_chain(_manifest(), install_dir)
    payload = json.loads(sbom.read_text(encoding="utf-8"))
    assert payload["bomFormat"] == "CycloneDX"
    assert payload["specVersion"] == "1.5"
    assert any(item["name"] == "requests" for item in payload["components"])
    assert any(item["name"] == "entry.py" for item in payload["components"])


def test_verify_supply_chain_rejects_bundled_skill_without_hash_manifest(tmp_path: Path) -> None:
    install_dir = tmp_path / "extensions" / "installed" / "demo-skill"
    install_dir.mkdir(parents=True)
    (install_dir / "entry.py").write_text("print('ok')\n", encoding="utf-8")
    with pytest.raises(SkillInvocationError, match="信任锚缺失"):
        verify_supply_chain(_manifest(trust="bundled"), install_dir)


def test_register_bundled_trust_anchor_copies_hash_manifest(tmp_path: Path) -> None:
    install_dir = tmp_path / "extensions" / "installed" / "demo-skill"
    install_dir.mkdir(parents=True)
    bundled_hash_manifest_path(install_dir).write_text(
        json.dumps({"files": {"entry.py": "abc"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    target = register_bundled_trust_anchor(install_dir, "demo-skill")
    assert target == host_trust_anchor_path(install_dir, "demo-skill")
    assert target.is_file()


def test_audit_supply_chain_failure_exposes_audit_fields_only(tmp_path: Path) -> None:
    install_dir = tmp_path / "extensions" / "installed" / "demo-skill"
    install_dir.mkdir(parents=True)
    try:
        verify_supply_chain(_manifest(trust="bundled"), install_dir)
    except SkillInvocationError as exc:
        audit = audit_supply_chain_failure(exc, skill_name="demo-skill", path="entry.py")
    else:
        raise AssertionError("expected supply chain failure")
    assert audit["skill_id"] == "demo-skill"
    assert audit["path"] == "entry.py"
    assert audit["error_code"] == "E_SKILL_TRUST_ANCHOR_MISSING"
