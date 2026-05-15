"""session：人格锁与会话装配占位（B1）。"""

from __future__ import annotations

from offline_companion.shared.types import Persona


class PersonaSessionCore:
    """摘要：围绕单一人设的会话核占位；后续承接上下文装配。"""

    def __init__(self, persona: Persona) -> None:
        self.persona = persona

    @property
    def system_prompt_locked(self) -> str:
        """摘要：返回受角色锁约束的系统提示文本。"""
        return self.persona.system_prompt if self.persona.role_lock else self.persona.system_prompt
