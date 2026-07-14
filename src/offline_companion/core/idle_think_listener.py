"""idle_think_listener：空闲思考触发监听器与编排桥接。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from offline_companion.core.plan_orchestrator import PlanOrchestrator
from offline_companion.core.state_manager import StateManager

IdleThinkCallback = Callable[[], None]


@dataclass
class IdleThinkListener:
    """摘要：监听系统空闲信号并触发 IdleThink。"""

    state_manager: StateManager
    on_idle_think: IdleThinkCallback
    _armed: bool = field(default=False, init=False)

    def arm(self) -> None:
        """摘要：注册监听器。"""
        if self._armed:
            return
        self.state_manager.subscribe("system", "idle_think_requested", self._handle_idle_signal)
        self._armed = True

    def disarm(self) -> None:
        """摘要：取消监听器。"""
        if not self._armed:
            return
        self.state_manager.unsubscribe("system", "idle_think_requested", self._handle_idle_signal)
        self._armed = False

    def _handle_idle_signal(self, new_record, old_record) -> None:
        if bool(new_record.value):
            self.on_idle_think()


@dataclass
class IdleThinkOrchestratorBridge:
    """摘要：连接 StateManager → IdleThinkListener → PlanOrchestrator 的真实桥接层。"""

    state_manager: StateManager
    plan_orchestrator: PlanOrchestrator
    skill_invoker: Any
    skill_install_dir: Path
    skill_manifest_factory: Callable[[str], Any] | None = None
    plan_id: str = "idle_think"
    _listener: IdleThinkListener | None = field(default=None, init=False)

    def arm(self) -> None:
        """摘要：挂接空闲监听与编排器。"""
        if self._listener is not None:
            return
        self._listener = IdleThinkListener(self.state_manager, self._on_idle_think)
        self._listener.arm()

    def disarm(self) -> None:
        """摘要：解除挂接。"""
        if self._listener is None:
            return
        self._listener.disarm()
        self._listener = None

    def _default_invoke_skill(self, step: Any, context: Any) -> Any:
        manifest_factory = self.skill_manifest_factory or self._default_manifest_factory
        manifest = manifest_factory(getattr(step, "skill_id", "idle_think_step"))
        process = self.skill_invoker.start(manifest, self.skill_install_dir)
        try:
            return {
                "step_id": getattr(step, "step_id", None),
                "skill_id": getattr(step, "skill_id", None),
                "port": process.port,
                "status": "started",
            }
        finally:
            self.skill_invoker.stop(manifest.name)

    def _default_manifest_factory(self, skill_id: str) -> Any:
        return {
            "name": skill_id,
            "version": None,
            "version_raw": "0.0.0",
            "description": "idle think placeholder skill",
            "market_id": f"{skill_id}@0.0.0",
            "trust": "user_installed",
            "entrypoint": {
                "type": "local_api",
                "host": "127.0.0.1",
                "port": 0,
                "path": "/entry.py",
            },
            "permissions": (),
            "required_api_keys": (),
            "output_mode": "block",
            "raw": {},
        }

    def _on_idle_think(self) -> None:
        self.plan_orchestrator.execute_plan(
            self.plan_id,
            invoke_skill=self._default_invoke_skill,
        )
