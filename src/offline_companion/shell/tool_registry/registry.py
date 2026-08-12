"""registry：Tool 注册、外部配置加载与权限解析。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml

from offline_companion.shared.runtime_paths import configs_dir
from offline_companion.shared.types import PrivacyMode, ToolManifest

BuiltinToolHandler = Callable[..., dict[str, object]]

_NETWORK_SCOPES = frozenset({"network_egress", "cloud_inference"})


class ToolRegistry:
    """摘要：A2 层 Tool 注册中心。

    Builtin Tool 由代码注册并提供 handler；
    External Tool 由 YAML 清单加载，仅记录元数据与启用状态。
    """

    def __init__(self, external_config_path: Path | None = None) -> None:
        self._tools: dict[str, ToolManifest] = {}
        self._builtin_handlers: dict[str, BuiltinToolHandler] = {}
        self._session_context_tools: set[str] = set()
        self._external_config_path = external_config_path

    @property
    def external_config_path(self) -> Path:
        """摘要：返回 external Tool 配置路径。"""
        if self._external_config_path is not None:
            return self._external_config_path
        return configs_dir() / "tools_external.yaml"

    def register_builtin(
        self,
        manifest: ToolManifest,
        handler: BuiltinToolHandler,
        *,
        inject_session_id: bool = False,
    ) -> None:
        """摘要：注册 builtin Tool。"""
        if manifest.tool_type != "builtin":
            raise ValueError("builtin registration requires tool_type='builtin'")
        if manifest.permission == "deny":
            raise ValueError("builtin tool with permission='deny' should not be registered")
        self._tools[manifest.tool_id] = manifest
        self._builtin_handlers[manifest.tool_id] = handler
        if inject_session_id:
            self._session_context_tools.add(manifest.tool_id)

    def load_external(self, config_path: Path | None = None) -> list[ToolManifest]:
        """摘要：从 YAML 加载 external Tool 清单。"""
        path = config_path or self.external_config_path
        if not path.is_file():
            return []
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items = raw.get("tools", []) if isinstance(raw, dict) else []
        manifests: list[ToolManifest] = []
        for item in items:
            if not isinstance(item, dict):
                raise TypeError("external tool item must be a mapping")
            permission = str(item.get("permission") or "deny")
            if permission == "allow":
                raise ValueError("external tool permission cannot be 'allow'")
            if permission not in {"ask", "deny"}:
                raise ValueError(f"unsupported external tool permission: {permission}")
            tool_id = str(item.get("tool_id") or "").strip()
            endpoint = str(item.get("endpoint") or "").strip()
            if not tool_id or not endpoint:
                raise ValueError("external tool requires non-empty tool_id and endpoint")
            manifest = ToolManifest(
                tool_id=tool_id,
                display_name=str(item.get("display_name") or tool_id),
                description=str(item.get("description") or ""),
                tool_type="external",
                permission=permission,
                scope=str(item.get("scope") or "network_egress"),
                params_schema=_dict_field(item.get("params_schema")),
                return_schema=_dict_field(item.get("return_schema")),
                handler_module=None,
                handler_function=None,
                external_config=tool_id,
                version=str(item.get("version") or "0.1.0"),
                audit_only=True,
                enabled=bool(item.get("enabled", False)),
                endpoint=endpoint,
            )
            self._tools[tool_id] = manifest
            manifests.append(manifest)
        return manifests

    def set_external_enabled(self, tool_id: str, enabled: bool) -> ToolManifest:
        """摘要：切换 external Tool 的启用状态。"""
        manifest = self.require_manifest(tool_id)
        if manifest.tool_type != "external":
            raise ValueError("only external tools support enabled state changes")
        updated = ToolManifest(
            tool_id=manifest.tool_id,
            display_name=manifest.display_name,
            description=manifest.description,
            tool_type=manifest.tool_type,
            permission=manifest.permission,
            scope=manifest.scope,
            params_schema=dict(manifest.params_schema),
            return_schema=dict(manifest.return_schema),
            handler_module=manifest.handler_module,
            handler_function=manifest.handler_function,
            external_config=manifest.external_config,
            version=manifest.version,
            audit_only=manifest.audit_only,
            enabled=enabled,
            endpoint=manifest.endpoint,
        )
        self._tools[tool_id] = updated
        return updated

    def list_available(self) -> list[ToolManifest]:
        """摘要：返回当前已注册且未显式 deny 的 Tool 清单。"""
        return [
            manifest
            for manifest in self._tools.values()
            if manifest.permission != "deny"
            and not (manifest.tool_type == "external" and not manifest.enabled)
        ]

    def get_manifest(self, tool_id: str) -> ToolManifest | None:
        """摘要：按 tool_id 获取清单。"""
        return self._tools.get(tool_id)

    def require_manifest(self, tool_id: str) -> ToolManifest:
        """摘要：获取清单，缺失时抛出 KeyError。"""
        manifest = self.get_manifest(tool_id)
        if manifest is None:
            raise KeyError(f"unknown tool_id: {tool_id}")
        return manifest

    def get_builtin_handler(self, tool_id: str) -> BuiltinToolHandler:
        """摘要：按 tool_id 获取 builtin handler。"""
        handler = self._builtin_handlers.get(tool_id)
        if handler is None:
            raise KeyError(f"unknown builtin handler: {tool_id}")
        return handler

    def injects_session_id(self, tool_id: str) -> bool:
        """摘要：判断 builtin Tool 是否由宿主注入可信 session_id。"""
        return tool_id in self._session_context_tools

    def resolve_permission(self, tool_id: str, *, privacy_mode: PrivacyMode) -> str:
        """摘要：解析 Tool 当前执行权限。"""
        manifest = self.require_manifest(tool_id)
        if privacy_mode is PrivacyMode.LOCAL_ONLY and manifest.scope in _NETWORK_SCOPES:
            return "deny"
        if manifest.tool_type == "external" and not manifest.enabled:
            return "deny"
        return manifest.permission


def _dict_field(value: object) -> dict[str, object]:
    """摘要：将配置字段规范化为字典。"""
    return dict(value) if isinstance(value, dict) else {}
