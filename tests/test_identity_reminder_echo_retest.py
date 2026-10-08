"""摘要：身份提醒回显聚焦 runner 的机械判定测试。"""

from __future__ import annotations

import importlib
import sys
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

runner = importlib.import_module("run_identity_reminder_echo_retest")


def test_identity_reminder_echo_retest_accepts_honest_identity_reply() -> None:
    """摘要：正常自称只要含身份关键词且无旧特征串即可通过。"""

    result = runner.evaluate_reply("我是助手一号，也是运行在本机的 AI。")

    assert result["old_feature_absent"] is True
    assert result["identity_keyword_hits"] == ["ai", "助手"]
    assert result["identity_acknowledged"] is True
    assert result["passed"] is True


def test_identity_reminder_echo_retest_rejects_old_feature_and_missing_identity() -> None:
    """摘要：旧特征回显或缺少身份承认都必须机械判红。"""

    echoed = runner.evaluate_reply("我不会滑向通用“语言模型/没有性格”腔。")
    vague = runner.evaluate_reply("我会一直陪你聊下去。")

    assert echoed["old_feature_count"] == 1
    assert echoed["passed"] is False
    assert vague["identity_acknowledged"] is False
    assert vague["passed"] is False


def test_echo_retest_records_complete_top_level_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要：三 seed 产物顶层保留完整 Git 与配置指纹 provenance。"""

    model = tmp_path / "model.gguf"
    persona = tmp_path / "persona.yaml"
    model.write_bytes(b"model")
    persona.write_text("persona_id: test\n", encoding="utf-8")
    args = Namespace(
        model=model,
        persona=persona,
        max_tokens=64,
        n_ctx=512,
        n_gpu_layers=0,
        verbose=False,
        skip_health_check=True,
    )
    monkeypatch.setattr(
        runner,
        "installed_distribution_version",
        lambda _name: "0.3.0-test",
    )
    monkeypatch.setattr(runner, "_load_persona", lambda _path: object())
    monkeypatch.setattr(
        runner,
        "_run_seed",
        lambda _args, *, seed, persona: {"seed": seed, "passed": True},
    )

    provenance = runner._collect_provenance(args)
    payload = runner.run_retest(args, provenance)

    assert {
        "created_at",
        "git_commit",
        "git_dirty",
        "worktree_fingerprint",
        "config_fingerprint",
        "resumed_history",
        "code_drift_detected",
        "config_drift_detected",
    } <= set(provenance)
    assert set(provenance["config_fingerprint"]["config"]) == {
        "model",
        "seeds",
        "sampling",
        "switches",
        "input_files",
    }
    assert payload["provenance"] == provenance
    assert "provenance" not in payload["meta"]


def test_echo_retest_collects_provenance_before_run_and_output_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """摘要：provenance 采集必须先于生成与任何审计 JSON 写入。"""

    events: list[str] = []
    provenance = {"git_commit": "a" * 40}
    monkeypatch.setattr(
        runner,
        "_collect_provenance",
        lambda _args: events.append("provenance") or provenance,
    )
    monkeypatch.setattr(
        runner,
        "run_retest",
        lambda _args, _provenance: events.append("run")
        or {"summary": {"all_passed": True}},
    )
    monkeypatch.setattr(
        runner,
        "_write_json",
        lambda _path, _payload: events.append("write"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_identity_reminder_echo_retest.py",
            "--model",
            str(tmp_path / "model.gguf"),
            "--persona",
            str(tmp_path / "persona.yaml"),
            "--output",
            str(tmp_path / "output.json"),
        ],
    )

    assert runner.main() == 0
    assert events == ["provenance", "run", "write"]
