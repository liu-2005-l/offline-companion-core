"""runtime：桌面壳会话运行时（扩展 UI 状态字段）。"""

from __future__ import annotations

from dataclasses import dataclass

from offline_companion.shell.ui_host.bootstrap import UISessionBundle
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shared.types import PrivacyMode


@dataclass
class DesktopRuntime:
    """摘要：桌面壳运行时（编排器 + 底栏/侧栏展示字段）。"""

    orchestrator: ConversationOrchestrator
    memory_on: bool
    session_id: str
    persona_name: str
    privacy_mode: PrivacyMode
    model_label: str

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
        )
