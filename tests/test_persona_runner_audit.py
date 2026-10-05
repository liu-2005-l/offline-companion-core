"""摘要：Runner provenance、checkpoint 与 candidate capture helper 窄测。"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from offline_companion.core.persona_constraint import PersonaL4Decision
from offline_companion.core.persona_session.repetition_guard import (
    CrossTurnRepetitionDecision,
)

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

audit = importlib.import_module("persona_runner_audit")


def _declared(*, guard_enabled: bool = False, threshold: int = 0) -> dict[str, object]:
    return {
        "model": {"path": "model.gguf", "size": 10, "mtime": 1},
        "seeds": {"case": [42]},
        "sampling": {"max_tokens": 0, "llama_cpp": "0.3.0", "note": ""},
        "switches": {"guard_enabled": guard_enabled, "threshold": threshold},
        "input_files": {"cases": {"path": "cases.json", "sha256": "abc"}},
    }


def _provenance(
    *,
    commit: str = "a" * 40,
    worktree: str = "1" * 64,
    config: dict[str, object] | None = None,
    code_drift: bool = False,
    config_drift: bool = False,
) -> dict[str, object]:
    return {
        "created_at": "2026-10-05T00:00:00Z",
        "git_commit": commit,
        "git_dirty": False,
        "worktree_fingerprint": worktree,
        "config_fingerprint": audit.build_config_fingerprint(config or _declared()),
        "resumed_history": [],
        "code_drift_detected": code_drift,
        "config_drift_detected": config_drift,
    }


def test_checkpoint_v1_save_and_full_load_has_frozen_fields(tmp_path) -> None:
    """摘要：新 checkpoint 包裹结构与 provenance 字段白名单固定。"""

    path = tmp_path / "checkpoint.json"
    provenance = _provenance()
    audit.save_checkpoint(path, {"cases": [1]}, provenance, [{"id": "capture"}])

    loaded = audit.load_checkpoint_full(path)

    assert set(loaded) == {"provenance_schema", "provenance", "captures", "payload"}
    assert loaded["provenance_schema"] == 1
    assert set(loaded["provenance"]) == {
        "created_at",
        "git_commit",
        "git_dirty",
        "worktree_fingerprint",
        "config_fingerprint",
        "resumed_history",
        "code_drift_detected",
        "config_drift_detected",
    }
    assert loaded["captures"] == [{"id": "capture"}]
    assert loaded["payload"] == {"cases": [1]}


def test_collect_git_state_rejects_git_failure_and_empty_head(monkeypatch) -> None:
    """摘要：Git 子命令失败或空 HEAD 都拒绝生成伪 provenance。"""

    def failed_run(*args, **kwargs):
        del args, kwargs
        raise subprocess.CalledProcessError(1, ["git", "rev-parse", "HEAD"])

    monkeypatch.setattr(audit.subprocess, "run", failed_run)
    with pytest.raises(audit.RunnerProvenanceError, match="仓库根目录"):
        audit.collect_git_state()

    monkeypatch.setattr(audit, "_run_git_bytes", lambda *args: b"")
    with pytest.raises(audit.RunnerProvenanceError, match="空输出"):
        audit.collect_git_state()


def test_collect_git_state_accepts_clean_porcelain(monkeypatch) -> None:
    """摘要：空 porcelain 是合法 clean，空 diff 与 untracked 仍生成稳定指纹。"""

    def fake_git(*args: str) -> bytes:
        if args == ("rev-parse", "HEAD"):
            return b"a" * 40 + b"\n"
        if args == ("status", "--porcelain"):
            return b"\n"
        return b""

    monkeypatch.setattr(audit, "_run_git_bytes", fake_git)
    state = audit.collect_git_state()
    empty_sha = hashlib.sha256(b"").hexdigest()
    expected = hashlib.sha256(f"{empty_sha}{empty_sha}".encode("ascii")).hexdigest()

    assert state == {
        "git_commit": "a" * 40,
        "git_dirty": False,
        "worktree_fingerprint": expected,
    }


def test_worktree_fingerprint_is_deterministic_and_distinguishes_diff(monkeypatch) -> None:
    """摘要：相同工作树输入同指纹，tracked diff 变化必翻转指纹。"""

    diff = b"diff --git a/a b/a\n"

    def fake_git(*args: str) -> bytes:
        return diff if args == ("diff", "--binary", "HEAD") else b""

    monkeypatch.setattr(audit, "_run_git_bytes", fake_git)
    first = audit.compute_worktree_fingerprint()
    second = audit.compute_worktree_fingerprint()
    diff = b"diff --git a/a b/a\n+changed\n"
    changed = audit.compute_worktree_fingerprint()

    assert first == second
    assert changed != first


def test_config_fingerprint_keeps_falsy_values_and_rejects_missing_or_none() -> None:
    """摘要：False、0、空串合法；缺少五类键或任意 None 必须失败。"""

    declared = _declared(guard_enabled=False, threshold=0)
    fingerprint = audit.build_config_fingerprint(declared)

    assert fingerprint["config"]["switches"]["guard_enabled"] is False
    assert fingerprint["config"]["switches"]["threshold"] == 0
    assert fingerprint["config"]["sampling"]["note"] == ""

    missing = dict(declared)
    missing.pop("model")
    with pytest.raises(audit.RunnerProvenanceError, match="model"):
        audit.build_config_fingerprint(missing)

    invalid = _declared()
    invalid["switches"] = {"guard_enabled": None}
    with pytest.raises(audit.RunnerProvenanceError, match="None"):
        audit.build_config_fingerprint(invalid)


def test_reconcile_resume_reports_sticky_code_and_config_drift(monkeypatch) -> None:
    """摘要：三维漂移可见，配置差异报键名，旧 sticky 标志不回落。"""

    monkeypatch.setattr(audit, "_utc_now", lambda: "2026-10-05T01:00:00Z")
    previous = _provenance(code_drift=True)
    current_config = _declared(guard_enabled=True)
    current = _provenance(
        commit="b" * 40,
        worktree="2" * 64,
        config=current_config,
    )

    result = audit.reconcile_resume({"provenance": previous}, current)

    assert result["legacy"] is False
    assert result["provenance"]["code_drift_detected"] is True
    assert result["provenance"]["config_drift_detected"] is True
    assert any("git_commit" in warning for warning in result["warnings"])
    assert any("worktree_fingerprint" in warning for warning in result["warnings"])
    assert any("switches.guard_enabled" in warning for warning in result["warnings"])
    assert result["provenance"]["resumed_history"] == [
        {
            "resumed_at": "2026-10-05T01:00:00Z",
            "git_commit": "b" * 40,
            "git_dirty": False,
            "worktree_fingerprint": "2" * 64,
        }
    ]

    sticky_previous = _provenance(code_drift=True, config_drift=True)
    same = audit.reconcile_resume({"provenance": sticky_previous}, sticky_previous)
    assert same["warnings"] == []
    assert same["provenance"]["code_drift_detected"] is True
    assert same["provenance"]["config_drift_detected"] is True


def test_legacy_checkpoint_warns_without_backfill_and_payload_stays_flat(tmp_path) -> None:
    """摘要：Legacy checkpoint 不回填 provenance，业务 payload 原样返回。"""

    path = tmp_path / "legacy.json"
    legacy = {"cases": [{"id": "S01"}], "metrics": {"aggregate": {}}}
    path.write_text(json.dumps(legacy), encoding="utf-8")

    full = audit.load_checkpoint_full(path)
    result = audit.reconcile_resume(full, _provenance())

    assert result == {
        "provenance": None,
        "warnings": ["legacy_provenance_missing"],
        "legacy": True,
    }
    assert audit.load_checkpoint_payload(path) == legacy
    assert audit.load_checkpoint_full(path) == legacy


def test_capture_sink_accepts_real_decision_dtos_and_deepcopies_them() -> None:
    """摘要：Capture sink 可直接深拷贝 core 使用的真实双门 decision DTO。"""

    sink = audit.CaptureSink()
    l4_decision = PersonaL4Decision(action="direct")
    repetition_decision = CrossTurnRepetitionDecision(
        action="retry",
        score=0.090909090909,
        threshold=0.09,
        reason="threshold_exceeded",
    )
    sink.push("first", "候选正文", l4_decision, repetition_decision)

    captured = sink.drain()

    assert captured[0]["l4_decision"] == l4_decision
    assert captured[0]["l4_decision"] is not l4_decision
    assert captured[0]["repetition_decision"] == repetition_decision
    assert captured[0]["repetition_decision"] is not repetition_decision
    assert captured[0]["repetition_decision"].score == 0.090909090909
    assert sink.drain() == []


def test_capture_sink_drains_and_builds_sidecar_from_persisted_matrix(tmp_path) -> None:
    """摘要：Sidecar 哈希取自已落盘矩阵读回字节，legacy 缺口显式在场。"""

    sink = audit.CaptureSink()
    l4_decision = {"action": "direct", "family": None}
    repetition_decision = {"action": "retry", "score": 0.090909090909}
    sink.push("first", "候选正文", l4_decision, repetition_decision)
    l4_decision["action"] = "retry"
    repetition_decision["score"] = 0.0
    captured = sink.drain()
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_bytes(b'{"meta":{}}\n')
    sidecar = audit.build_sidecar(
        captured,
        matrix_path,
        matrix_path.read_bytes(),
        "legacy_checkpoint_without_capture",
    )

    assert captured[0]["l4_decision"]["action"] == "direct"
    assert captured[0]["repetition_decision"]["score"] == 0.090909090909
    assert sidecar["meta"]["capture_complete"] is False
    assert sidecar["meta"]["legacy_gap"] == "legacy_checkpoint_without_capture"
    assert sidecar["meta"]["matrix_sha256"] == hashlib.sha256(b'{"meta":{}}\n').hexdigest()
    assert sidecar["capture_rows"] == captured


@pytest.mark.parametrize("content", ["{not-json", "[]"])
def test_checkpoint_load_rejects_corrupt_or_non_object_root(tmp_path, content) -> None:
    """摘要：损坏 JSON 与非对象根节点均 fail-fast，不把错误推迟到矩阵聚合。"""

    path = tmp_path / "broken.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(audit.RunnerProvenanceError):
        audit.load_checkpoint_full(path)
    with pytest.raises(audit.RunnerProvenanceError):
        audit.load_checkpoint_payload(path)


def test_load_checkpoint_payload_strips_new_wrapper_without_mutating_payload(tmp_path) -> None:
    """摘要：新 checkpoint 只返回 payload，审计段不会漂入矩阵结构。"""

    path = tmp_path / "new.json"
    payload = {"validation_cases": [], "validation_metrics": {}}
    audit.save_checkpoint(path, payload, _provenance(), [])

    assert audit.load_checkpoint_payload(path) == payload
    assert set(audit.load_checkpoint_full(path)) == {
        "provenance_schema",
        "provenance",
        "captures",
        "payload",
    }
