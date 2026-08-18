"""本地 UI 标注与私人 Skill 包生成能力。"""

from .automation import UIAutomationSession, UISequenceResult, UIStep
from .capability import capability_warnings, is_ui_automation_available
from .danger_detector import detect_danger
from .locator import LocateResult, LocatorCache, PageLocator
from .page_identifier import PageIdentifier
from .session import AnnotationError, AnnotationSession

__all__ = [
    "AnnotationError",
    "AnnotationSession",
    "LocateResult",
    "LocatorCache",
    "PageIdentifier",
    "PageLocator",
    "UIAutomationSession",
    "UISequenceResult",
    "UIStep",
    "capability_warnings",
    "detect_danger",
    "is_ui_automation_available",
]
