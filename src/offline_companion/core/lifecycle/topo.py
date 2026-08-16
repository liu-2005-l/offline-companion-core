"""插件依赖拓扑排序。"""

from __future__ import annotations

from collections import deque

from .config import PluginConfigEntry


class DependencyGraphError(ValueError):
    """插件依赖图非法。"""


class MissingDependencyError(DependencyGraphError):
    """依赖未在启用配置中定义。"""


class CircularDependencyError(DependencyGraphError):
    """依赖图包含循环。"""


def topological_sort(plugins: list[PluginConfigEntry] | tuple[PluginConfigEntry, ...]) -> list[PluginConfigEntry]:
    """摘要：按依赖先后稳定排序已启用插件。"""
    entries = [plugin for plugin in plugins if plugin.enabled]
    id_map = {plugin.id: plugin for plugin in entries}
    in_degree = {plugin.id: 0 for plugin in entries}
    edges = {plugin.id: [] for plugin in entries}
    for plugin in entries:
        for required in plugin.requires:
            if required not in id_map:
                raise MissingDependencyError(
                    f"Plugin {plugin.id!r} requires {required!r} which is not enabled"
                )
            edges[required].append(plugin.id)
            in_degree[plugin.id] += 1
    queue = deque(plugin.id for plugin in entries if in_degree[plugin.id] == 0)
    result: list[PluginConfigEntry] = []
    while queue:
        plugin_id = queue.popleft()
        result.append(id_map[plugin_id])
        for dependent in edges[plugin_id]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    if len(result) != len(entries):
        remaining = [plugin_id for plugin_id, degree in in_degree.items() if degree]
        raise CircularDependencyError(f"Circular dependency detected: {remaining}")
    return result
