"""CLI 单轮同意交互测试。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.shared.types import TurnResult
from offline_companion.shell.ui_host.cli import _default_persona_path, _resolve_cli_consent


class _StubGateway:
    """摘要：提供固定 modal payload 的测试网关。"""

    def to_modal_payload(self, request_id: str | None = None) -> dict[str, object]:
        return {
            "title": "云端路由需要同意",
            "body": "本轮将把当前问题发送到云端模型。",
            "request_id": request_id,
        }


class _StubOrchestrator:
    """摘要：记录恢复调用的最小编排器桩。"""

    def __init__(self, resumed: TurnResult) -> None:
        self.consent_gateway = _StubGateway()
        self._resumed = resumed
        self.calls: list[tuple[str, bool]] = []

    def resume_pending_turn(self, request_id: str, *, allowed: bool) -> TurnResult:
        self.calls.append((request_id, allowed))
        return self._resumed


def test_resolve_cli_consent_allows_pending_turn(monkeypatch) -> None:
    resumed = TurnResult(reply="云端已恢复", route_mode="cloud")
    orchestrator = _StubOrchestrator(resumed)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    result = _resolve_cli_consent(
        orchestrator,  # type: ignore[arg-type]
        TurnResult(
            requires_consent=True,
            consent_request_id="req-1",
            estimated_cost=0.02,
        ),
    )

    assert result.reply == "云端已恢复"
    assert orchestrator.calls == [("req-1", True)]


def test_resolve_cli_consent_reprompts_then_denies(monkeypatch) -> None:
    resumed = TurnResult(reply="已取消本轮云端请求。", route_mode="cloud")
    orchestrator = _StubOrchestrator(resumed)
    answers = iter(["maybe", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    result = _resolve_cli_consent(
        orchestrator,  # type: ignore[arg-type]
        TurnResult(
            requires_consent=True,
            consent_request_id="req-2",
            estimated_cost=0.01,
        ),
    )

    assert result.reply == "已取消本轮云端请求。"
    assert orchestrator.calls == [("req-2", False)]


def test_default_persona_path_is_absolute_and_existing(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OFFLINE_COMPANION_PERSONA_PATH", raising=False)

    persona_path = Path(_default_persona_path())

    assert persona_path.is_absolute()
    assert persona_path.is_file()
