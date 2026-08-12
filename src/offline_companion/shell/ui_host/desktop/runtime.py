"""runtime：桌面壳会话运行时（扩展 UI 状态字段）。"""

from __future__ import annotations

from dataclasses import dataclass

from offline_companion.core.memory_lifecycle.triggers import TriggerRegistry
from offline_companion.core.plan_orchestrator import PlanOrchestrator
from offline_companion.core.state_manager import StateManager
from offline_companion.shared.types import AppPaths, PrivacyMode
from offline_companion.shell.auto_turn_orchestrator import AutoTurnOrchestrator
from offline_companion.shell.idle_think_coordinator import IdleThinkCoordinator
from offline_companion.shell.ui_host.bootstrap import UISessionBundle
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.idle_detector import IdleDetector


@dataclass
class DesktopRuntime:
    """摘要：桌面壳运行时（编排器 + 底栏/侧栏展示字段）。"""

    orchestrator: ConversationOrchestrator
    memory_on: bool
    session_id: str
    persona_name: str
    privacy_mode: PrivacyMode
    model_label: str
    triggers: TriggerRegistry
    paths: AppPaths
    socket_guard_enabled: bool = False
    plan_orchestrator: PlanOrchestrator | None = None
    auto_turn_orchestrator: AutoTurnOrchestrator | None = None
    idle_detector: IdleDetector | None = None
    idle_coordinator: IdleThinkCoordinator | None = None
    state_manager: StateManager | None = None

    @classmethod
    def from_bundle(cls, bundle: UISessionBundle) -> DesktopRuntime:
        """摘要：由 ``bootstrap_ui_session`` 结果构造桌面运行时。"""
        return cls(
            orchestrator=bundle.orchestrator,
            memory_on=bundle.memory_on,
            session_id=bundle.session_id,
            persona_name=bundle.persona_name,
            privacy_mode=bundle.privacy_mode,
            model_label=bundle.model_label,
            triggers=TriggerRegistry(version=1, path=bundle.paths.root / "triggers.yaml", enabled={"on_summarize_request": False, "on_explicit_save": True, "on_emotion_shift": False}),
            paths=bundle.paths,
            plan_orchestrator=bundle.plan_orchestrator,
            auto_turn_orchestrator=bundle.auto_turn_orchestrator,
            idle_detector=bundle.idle_detector,
            idle_coordinator=bundle.idle_coordinator,
            state_manager=bundle.state_manager,
        )
