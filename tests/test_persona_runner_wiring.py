"""摘要：W2/P2-2 runner provenance、checkpoint 与 capture 接线验收。"""

from __future__ import annotations

import inspect
import json
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any

import scripts.persona_runner_audit as audit
import scripts.run_persona_expression_w2 as w2_runner
import scripts.run_w3_p2_repetition_retest as p2_runner

from offline_companion.core.persona_session.repetition_guard import (
    CrossTurnRepetitionDecision,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _provenance() -> dict[str, Any]:
    config = audit.build_config_fingerprint(
        {
            "model": {"backend": "echo"},
            "seeds": {"case": [42, 1337]},
            "sampling": {"max_tokens": 32},
            "switches": {"guard_enabled": True},
            "input_files": {"cases": {"sha256": "fixture"}},
        }
    )
    return {
        "created_at": "2026-10-08T00:00:00Z",
        "git_commit": "a" * 40,
        "git_dirty": False,
        "worktree_fingerprint": "b" * 64,
        "config_fingerprint": config,
        "resumed_history": [],
        "code_drift_detected": False,
        "config_drift_detected": False,
    }


def _direct_trace() -> dict[str, Any]:
    return {
        "enabled": True,
        "first": {
            "action": "direct",
            "score": 0.0,
            "threshold": 0.09,
            "comparison": "gt",
            "previous_ngrams": 0,
            "current_ngrams": 0,
            "reason": "missing_previous_or_current_reply",
            "confirmation_intent": False,
        },
        "retry": None,
        "retry_taken": False,
        "outcome": "direct",
    }


def _checkpoint_payload(case_id: str) -> dict[str, Any]:
    case = {
        "id": case_id,
        "scenario": "chat",
        "group": case_id,
        "focus": [],
        "turns": [{"id": None, "user": "hello"}],
        "replies": ["safe reply"],
        "recall_counts": [0],
        "repetition_traces": [_direct_trace()],
        "l4_traces": [{"outcome": "bypass"}],
    }
    return {
        "cases": [case],
        "metrics": {"aggregate": {"cross_turn_4gram_jaccard_mean": 0.0}},
        "validation_cases": [],
        "validation_metrics": {
            "aggregate": {"cross_turn_4gram_jaccard_mean": 0.0}
        },
    }


def _capture_row(*, arm: str, seed: int, turn_index: int = 0) -> dict[str, Any]:
    decision = CrossTurnRepetitionDecision(
        action="direct",
        score=0.0,
        threshold=0.09,
        reason="threshold_not_matched",
    )
    return audit.build_capture_row(
        [
            {
                "phase": "first",
                "text": "safe reply",
                "l4_decision": None,
                "repetition_decision": decision,
            }
        ],
        runner="p2_retest",
        arm=arm,
        source_kind="case",
        seed=seed,
        scenario_id="S01",
        turn_index=turn_index,
    )


def test_p2_resume_keeps_old_capture_and_merges_new_seed(tmp_path: Path) -> None:
    """摘要：新格式 checkpoint resume 后旧 capture 与新生成轮次共同进入 sidecar。"""

    cases_path = tmp_path / "cases.json"
    validation_path = tmp_path / "validation.json"
    cases_path.write_text(
        json.dumps(
            {
                "memory_bundle": [],
                "cases": [
                    {
                        "id": "S01",
                        "scenario": "chat",
                        "turns": [{"user": "hello"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    validation_path.write_text(json.dumps({"cases": []}), encoding="utf-8")
    args = Namespace(
        cases=cases_path,
        validation_cases=validation_path,
        persona=tmp_path / "missing-persona.yaml",
        backend="echo",
        model=None,
        checkpoint_dir=tmp_path / "checkpoints",
        resume=True,
        max_tokens=32,
        n_ctx=128,
        n_gpu_layers=0,
        skip_health_check=True,
        verbose=False,
        case_seeds=(42, 1337),
        arms=("A",),
        skip_memory_check=True,
    )
    provenance = _provenance()
    old_capture = _capture_row(arm="A", seed=42)
    checkpoint = p2_runner._checkpoint_path(args, "A", 42)
    audit.save_checkpoint(
        checkpoint,
        _checkpoint_payload("S01"),
        provenance,
        [old_capture],
    )

    payload, captures, legacy_gaps = p2_runner.run_retest(args, provenance)
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(json.dumps(payload), encoding="utf-8")
    sidecar = audit.build_sidecar(
        captures,
        matrix_path,
        matrix_path.read_bytes(),
        ";".join(legacy_gaps) or None,
    )

    assert old_capture in captures
    assert any(row["seed"] == 1337 for row in captures)
    assert sidecar["meta"]["capture_complete"] is True
    assert sidecar["meta"]["legacy_gap"] is None


def test_capture_six_part_join_key_does_not_collide() -> None:
    """摘要：双臂同 seed/scenario 与同场景多轮均保持六元 join 键唯一。"""

    rows = [
        _capture_row(arm=arm, seed=42, turn_index=turn_index)
        for arm in ("A", "B")
        for turn_index in (0, 1)
    ]
    keys = {
        (
            row["runner"],
            row["arm"],
            row["source_kind"],
            row["seed"],
            row["scenario_id"],
            row["turn_index"],
        )
        for row in rows
    }

    assert len(keys) == len(rows) == 4


def test_runner_checkpoint_paths_have_no_raw_json_loader() -> None:
    """摘要：checkpoint 访问只经审计 helper，不保留 raw json.loads 旁路。"""

    functions = (
        w2_runner._resume_checkpoint,
        w2_runner._load_or_run_cases,
        w2_runner._load_or_run_probe,
        p2_runner._resume_checkpoint,
        p2_runner._run_arm_seed,
    )

    assert all("json.loads" not in inspect.getsource(function) for function in functions)


def test_ignored_runner_state_does_not_change_real_git_fingerprint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """摘要：真 Git 仓库中的 lock/checkpoint 受 ignore 后不污染 provenance。"""

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "runner@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Runner Test"],
        cwd=repo,
        check=True,
    )
    (repo / ".gitignore").write_text(
        "artifacts/persona_expression/w2_checkpoints/\n"
        "artifacts/persona_expression/w2_matrix.lock\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(audit, "REPO_ROOT", repo)
    before = audit.collect_git_state()
    checkpoint = repo / "artifacts/persona_expression/w2_checkpoints/seed42.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}", encoding="utf-8")
    lock = repo / "artifacts/persona_expression/w2_matrix.lock"
    lock.write_text("locked", encoding="utf-8")
    after = audit.collect_git_state()

    assert before["git_dirty"] is False
    assert after["git_dirty"] is False
    assert after["worktree_fingerprint"] == before["worktree_fingerprint"]


def test_wrapped_checkpoint_keeps_legacy_matrix_payload_shape(tmp_path: Path) -> None:
    """摘要：新 checkpoint 剥离后字段与 legacy 一致且 W2 汇总保持兼容。"""

    payload = {
        "cases": [{"id": "S01", "replies": ["safe"]}],
        "metrics": {"aggregate": {}},
    }
    legacy_path = tmp_path / "legacy.json"
    wrapped_path = tmp_path / "wrapped.json"
    legacy_path.write_text(json.dumps(payload), encoding="utf-8")
    audit.save_checkpoint(wrapped_path, payload, _provenance(), [])
    legacy = audit.load_checkpoint_payload(legacy_path)
    wrapped = audit.load_checkpoint_payload(wrapped_path)

    assert set(wrapped) == set(legacy)
    assert wrapped == legacy
    assert w2_runner._case_trace_summary({"seed42": wrapped}) == {
        "reply_count": 1
    }


def test_runners_use_audit_helper_as_single_git_fact_source() -> None:
    """摘要：两 runner 均接统一 helper，源码不得复制 Git provenance 命令。"""

    paths = (
        REPO_ROOT / "scripts/run_persona_expression_w2.py",
        REPO_ROOT / "scripts/run_w3_p2_repetition_retest.py",
    )
    forbidden = ("rev-parse", "--porcelain", "diff --binary")
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "from persona_runner_audit import" in source
        assert "build_provenance" in source
        assert all(token not in source for token in forbidden)
