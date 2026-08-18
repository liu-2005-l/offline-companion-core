"""UI 自动化安全执行链测试。"""

from __future__ import annotations

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.ui_annotation import (
    UIAutomationSession,
    UISequenceResult,
    UIStep,
    capability_warnings,
)


class _Consent:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = 0

    def submit(self, _request):
        self.calls += 1
        return self.allowed


class _Location:
    found = True
    x = 40
    y = 50
    error = None


class _Locator:
    def locate(self, _text, _region):
        return _Location()


class _Actor:
    def __init__(self, on_click=None):
        self.actions = []
        self.on_click = on_click

    def click(self, x, y):
        self.actions.append(("click", x, y))
        if self.on_click is not None:
            self.on_click()

    def input_text(self, value):
        self.actions.append(("input", value))


def test_sequence_uses_one_consent_and_audits_each_action() -> None:
    consent = _Consent()
    events = EventStream("ui", build_default_registry())
    actor = _Actor()
    session = UIAutomationSession(consent, _Locator(), actor, events)
    result = session.execute_sequence("发送消息", [UIStep("click", "搜索"), UIStep("input", "输入", value="你好")], "plan-1")
    assert result == UISequenceResult(success=True, completed_steps=2)
    assert consent.calls == 1
    recorded = events.get_events()
    assert len(recorded) == 2
    assert all(event.event_type == "ui/action_executed" for event in recorded)


def test_denied_consent_does_not_inject_input() -> None:
    actor = _Actor()
    result = UIAutomationSession(_Consent(False), _Locator(), actor).execute_sequence("危险操作", [UIStep("click", "删除", danger="hard")], "plan-1")
    assert result.consent_denied
    assert actor.actions == []


def test_hard_danger_requires_extra_consent() -> None:
    consent = _Consent()
    result = UIAutomationSession(consent, _Locator(), _Actor()).execute_sequence("删除", [UIStep("click", "删除", danger="hard")], "plan-1")
    assert result.success
    assert consent.calls == 2


def test_stop_interrupts_before_next_step() -> None:
    session_ref = []
    actor = _Actor(lambda: session_ref[0].stop())
    session = UIAutomationSession(_Consent(), _Locator(), actor)
    session_ref.append(session)
    result = session.execute_sequence("发送", [UIStep("click", "发送"), UIStep("click", "再次发送")], "plan-1")
    assert result.interrupted and result.completed_steps == 1


def test_ui_capability_warning_is_non_blocking() -> None:
    manifest = {"name": "demo", "capabilities": ["ui_automation"]}
    assert capability_warnings(manifest) in ([], ["声明 ui_automation，但本机未启用完整 UI 自动化依赖"])
