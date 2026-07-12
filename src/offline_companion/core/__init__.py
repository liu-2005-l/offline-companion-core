"""core：陪伴核（零公网；禁止依赖 shell）。"""

from .state_manager import StateManager as StateManager
from .state_manager import StateRecord as StateRecord

__all__ = ["StateManager", "StateRecord"]
