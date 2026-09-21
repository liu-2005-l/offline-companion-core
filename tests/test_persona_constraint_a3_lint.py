"""摘要：P3-A3 共享 lint API、全语料扫描与注入式正控。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from offline_companion.core.persona_constraint import (
    assistant_texts,
    detect_copy,
    disagreement_share,
    manifest_reference_issues,
    scan_absolute_promises,
    scan_forbidden,
    scan_l4,
    scan_literal_display_names,
    scan_mechanism_leaks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_shared_lint_api_accepts_all_published_assistant_text() -> None:
    manifest = _load(REPO_ROOT / "configs" / "persona_constraint_corpus.yaml")
    lexicon = _load(REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml")
    patterns = _load(REPO_ROOT / "configs" / "persona_constraint_l4_patterns.yaml")
    coverage = _load(REPO_ROOT / "configs" / "persona_constraint_example_coverage.yaml")
    source_payloads = [
        _load(REPO_ROOT / relative_path)
        for name, relative_path in manifest["sources"].items()
        if name in {"dimension_corpus", "structural_corpus", "reply_copy"}
    ]
    texts = tuple(text for payload in source_payloads for text in assistant_texts(payload))
    forbidden_names = coverage["structural_library"]["literal_display_names_forbidden"]

    assert texts
    assert manifest_reference_issues(manifest, REPO_ROOT) == ()
    for text in texts:
        assert scan_forbidden(text, lexicon) == []
        assert scan_l4(
            text,
            patterns,
            display_name_present="{display_name}" in text,
        )["hit"] is False
        assert scan_absolute_promises(text) == ()
        assert scan_mechanism_leaks(text) == ()
        assert scan_literal_display_names(text, forbidden_names) == ()


def test_shared_lint_rules_have_independent_injected_positive_controls(tmp_path: Path) -> None:
    lexicon = _load(REPO_ROOT / "configs" / "persona_constraint_lexicon.yaml")
    patterns = _load(REPO_ROOT / "configs" / "persona_constraint_l4_patterns.yaml")
    manifest = _load(REPO_ROOT / "configs" / "persona_constraint_corpus.yaml")

    assert scan_forbidden("作为一个AI助手，我不能陪伴你。", lexicon)
    assert scan_l4("我无法保持人格。", patterns, display_name_present=False)["hit"] is True
    assert detect_copy("先选你已经接触", ["先选你已经接触过的一项。"], 8)["hit"] is True
    assert disagreement_share(["comfort", "advice", "joy"]) < 0.25
    assert scan_literal_display_names("我是小岚。", ["小岚"]) == ("小岚",)
    assert scan_absolute_promises("我保证一定会完成。")
    assert scan_mechanism_leaks("L1 system prompt 的 SHA-256 已更新。")

    broken = dict(manifest)
    broken["sources"] = {**manifest["sources"], "missing": "configs/not-found.yaml"}
    assert "manifest_source_hash_keys_mismatch" in manifest_reference_issues(broken, tmp_path)
    assert any(issue.startswith("source_missing:") for issue in manifest_reference_issues(broken, tmp_path))
