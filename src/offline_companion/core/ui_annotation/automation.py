"""UI 自动化序列的 Consent、安全与审计执行器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from offline_companion.core.plan_orchestrator import ConsentRequest


class _ConsentGateway(Protocol):
    def submit(self, consent_request: ConsentRequest) -> bool: ...


class _Locator(Protocol):
    def locate(self, target_text: str, region: list[float]) -> Any: ...


class _Actor(Protocol):
    def click(self, x: int, y: int) -> None: ...

    def input_text(self, text: str) -> None: ...


@dataclass(frozen=True)
class UIStep:
    """摘要：一个待执行的 UI 操作步骤。"""

    action: str
    target_text: str = ""
    region: list[float] = field(default_factory=lambda: [0, 0, 100, 100])
    danger: str = "none"
    value: str = ""
    expected_page: str | None = None
    navigates_to: str | None = None

    def describe(self) -> str:
        """摘要：生成不包含输入原文的 Consent 描述。"""
        return f"{self.action}:{self.target_text or 'screen'}"


@dataclass(frozen=True)
class UISequenceResult:
    """摘要：UI 操作序列的可审计结果。"""

    success: bool = False
    consent_denied: bool = False
    interrupted: bool = False
    completed_steps: int = 0
    failed_step: int | None = None
    error: str | None = None
    actual_page: str | None = None


class UIAutomationSession:
    """摘要：以一次意图为粒度执行 UI 操作并 fail-closed。"""

    def __init__(self, consent_gateway: _ConsentGateway | None, locator: _Locator, actor: _Actor, event_stream: Any = None, page_identifier: Any = None) -> None:
        self._consent = consent_gateway
        self._locator = locator
        self._actor = actor
        self._events = event_stream
        self._identifier = page_identifier
        self._interrupted = False

    def stop(self) -> None:
        """摘要：请求在下一次输入注入前中止序列。"""
        self._interrupted = True

    def execute_sequence(self, intent: str, steps: list[UIStep], plan_id: str, *, skill_id: str = "ui-automation", pages: list[dict[str, Any]] | None = None) -> UISequenceResult:
        """摘要：完成一次序列级 Consent 后逐步定位、执行、验页。"""
        self._interrupted = False
        if self._consent is None:
            return UISequenceResult(consent_denied=True, error="E_CONSENT_UNAVAILABLE")
        risk = self._assess_risk(steps)
        request = ConsentRequest(
            plan_id=plan_id,
            step_id="ui-sequence",
            skill_id=skill_id,
            operation=intent,
            risk_level=risk,
            impact_scope="local_application",
            source="ui_automation",
            metadata={"steps_summary": [step.describe() for step in steps]},
        )
        if not self._consent.submit(request):
            return UISequenceResult(consent_denied=True, error="E_CONSENT_DENIED")
        if risk == "hard" and not self._consent.submit(request):
            return UISequenceResult(consent_denied=True, error="E_HARD_DANGER_DENIED")
        for index, step in enumerate(steps):
            if self._interrupted:
                return UISequenceResult(interrupted=True, completed_steps=index, error="E_UI_INTERRUPTED")
            result = self._execute_step(step, index)
            if not result.success:
                return result
            actual_page = self._check_page(step, pages)
            if step.navigates_to and actual_page != step.navigates_to:
                self._audit(step, index, "blocked", 0, 0, actual_page)
                return UISequenceResult(interrupted=True, completed_steps=index + 1, error="E_UNEXPECTED_PAGE", actual_page=actual_page)
        return UISequenceResult(success=True, completed_steps=len(steps))

    def _execute_step(self, step: UIStep, index: int) -> UISequenceResult:
        if step.action == "read":
            self._audit(step, index, "success", 0, 0, None)
            return UISequenceResult(success=True, completed_steps=index + 1)
        located = self._locator.locate(step.target_text, step.region)
        if not getattr(located, "found", False):
            self._audit(step, index, "failed", 0, 0, None)
            return UISequenceResult(failed_step=index, error=getattr(located, "error", None) or "E_UI_ELEMENT_NOT_FOUND")
        x, y = int(located.x), int(located.y)
        try:
            if step.action == "click":
                self._actor.click(x, y)
            elif step.action == "input":
                self._actor.click(x, y)
                self._actor.input_text(step.value)
            else:
                self._audit(step, index, "failed", x, y, None)
                return UISequenceResult(failed_step=index, error="E_UI_ACTION_UNSUPPORTED")
        except (OSError, RuntimeError, ValueError) as exc:
            self._audit(step, index, "failed", x, y, None)
            return UISequenceResult(failed_step=index, error=str(exc))
        self._audit(step, index, "success", x, y, None)
        return UISequenceResult(success=True, completed_steps=index + 1)

    def _check_page(self, step: UIStep, pages: list[dict[str, Any]] | None) -> str | None:
        if self._identifier is None or not pages or step.expected_page is None:
            return step.expected_page
        screenshot = getattr(self._actor, "read_screen", lambda: None)()
        return self._identifier.identify(pages, screenshot)

    def _audit(self, step: UIStep, index: int, result: str, x: int, y: int, page_id: str | None) -> None:
        if self._events is None:
            return
        self._events.append(
            "ui/action_executed",
            {
                "step_index": index,
                "action": step.action,
                "target_text": step.target_text,
                "coordinates": [x, y],
                "result": result,
                "danger_level": step.danger,
                "page_id": page_id,
            },
        )

    @staticmethod
    def _assess_risk(steps: list[UIStep]) -> str:
        if any(step.danger == "hard" for step in steps):
            return "hard"
        if any(step.danger == "soft" for step in steps):
            return "soft"
        return "none"
