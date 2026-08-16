"""插件生命周期基础设施。"""

from .context import PluginContext
from .effect_scope import EffectScope
from .fiber import DependencyError, PluginFiber
from .types import Cleanup, LifecycleState, PluginDefinition

__all__ = [
    "Cleanup",
    "DependencyError",
    "EffectScope",
    "LifecycleState",
    "PluginContext",
    "PluginDefinition",
    "PluginFiber",
]
