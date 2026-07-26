"""摘要：CI 检查脚本最小测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.ci.check_imports import main as check_imports_main
from scripts.ci.check_prompt_decoupling import main as check_prompt_main
from scripts.ci.check_prompt_decoupling import run_scan

from offline_companion.shell.skill_manager.capability_catalog import build_capability_keywords

pytestmark = pytest.mark.security


def test_check_imports_script_passes() -> None:
    """摘要：当前仓库应通过 AST 分层检查。"""
    assert check_imports_main() == 0


def test_check_prompt_decoupling_script_passes() -> None:
    """摘要：当前仓库应通过 prompt 解耦扫描。"""
    assert check_prompt_main([]) == 0


def test_check_prompt_decoupling_detects_forbidden_keyword(tmp_path: Path) -> None:
    """摘要：扫描器应命中由 manifest 自动生成的完整 Skill 名关键词。"""
    _install_fixture_manifest(tmp_path)
    target = tmp_path / "src" / "offline_companion" / "core" / "demo_prompt.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('PROMPT = "请调用 novel-writer 获取天气"\n', encoding="utf-8")

    errors = run_scan(tmp_path, targets=["src/offline_companion/core"])

    assert len(errors) == 1
    assert "novel-writer" in errors[0]


def test_check_prompt_decoupling_uses_full_keyword_boundary(tmp_path: Path) -> None:
    """摘要：子串不应误伤，仅完整关键词匹配。"""
    _install_fixture_manifest(tmp_path)
    target = tmp_path / "src" / "offline_companion" / "core" / "demo_prompt.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('PROMPT = "请生成 novel writer 摘要"\n', encoding="utf-8")

    errors = run_scan(tmp_path, targets=["src/offline_companion/core"])

    assert errors == []


def test_capability_catalog_extracts_manifest_keywords(tmp_path: Path) -> None:
    """摘要：能力目录应从 manifest 自动提取 Skill 名、入口、权限与 API 字段。"""
    _install_fixture_manifest(tmp_path)

    keywords = {item.value for item in build_capability_keywords(tmp_path)}

    assert "novel-writer" in keywords
    assert "novel-writer@1.2.0" in keywords
    assert "/v1/complete" in keywords
    assert "complete" in keywords
    assert "deepseek" in keywords
    assert "DEEPSEEK" in keywords
    assert "cloud_inference" in keywords


def test_capability_catalog_loads_decouple_probe_fixture(tmp_path: Path) -> None:
    """摘要：新增 Skill fixture 后，A 层关键词目录应自动提取其 manifest 细节。"""
    _install_fixture_manifest(tmp_path, fixture_name="decouple-probe")

    keywords = {item.value for item in build_capability_keywords(tmp_path)}

    assert "decouple-probe" in keywords
    assert "decouple-probe@0.1.0" in keywords
    assert "/v1/decouple_probe" in keywords
    assert "decouple_probe" in keywords
    assert "read_session_context" in keywords
    assert "decouple_probe_token" in keywords
    assert "DECOUPLE_PROBE_TOKEN" in keywords


def test_prompt_scan_still_passes_after_installing_decouple_probe_fixture(tmp_path: Path) -> None:
    """摘要：新增 Skill fixture 不应要求修改任何 B 层文件，扫描仍应通过。"""
    _install_fixture_manifest(tmp_path)
    _install_fixture_manifest(tmp_path, fixture_name="decouple-probe")
    target = tmp_path / "src" / "offline_companion" / "core" / "safe_prompt.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('PROMPT = "请继续保持温和、真诚、简洁的陪伴语气。"\n', encoding="utf-8")

    errors = run_scan(tmp_path, targets=["src/offline_companion/core"])

    assert errors == []


def _install_fixture_manifest(root: Path, *, fixture_name: str = "novel-writer") -> None:
    """摘要：把指定 fixture Skill manifest 安装到临时 data_root。"""
    install_dir = root / "extensions" / "installed" / fixture_name
    install_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(f"fixtures/skills/{fixture_name}/manifest.json").resolve()
    (install_dir / "manifest.json").write_text(
        manifest_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
