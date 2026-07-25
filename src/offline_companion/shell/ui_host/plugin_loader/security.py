"""摘要：Plugin iframe 隔离、Bridge 白名单与会话校验。"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime


class PluginSecurityError(RuntimeError):
    """摘要：Plugin 安全校验失败。"""


@dataclass(frozen=True)
class PluginManifest:
    """摘要：宿主侧可信 Plugin 清单。

    参数：
        plugin_id: Plugin 唯一标识。
        version: Plugin 版本。
        description: Plugin 描述。
        permissions: manifest 声明的权限集合。
        capabilities: 宿主授予的 Bridge 能力集合。
    """

    plugin_id: str
    version: str
    description: str
    permissions: tuple[str, ...]
    capabilities: tuple[str, ...]


@dataclass
class PluginRuntimeSession:
    """摘要：一次 iframe 挂载生命周期对应的安全会话。"""

    session_id: str
    session_token: str
    plugin_id: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    active: bool = True
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    def record(self, event: str, **payload: Any) -> None:
        """摘要：记录宿主侧审计事件。"""
        self.audit_log.append({"event": event, **payload})


@dataclass(frozen=True)
class CapabilitySchema:
    """摘要：宿主定义的 Bridge 能力 schema。"""

    capability: str
    required_permission: str
    risk_level: str
    validator: Callable[[dict[str, Any]], None]


class PluginSecurityGateway:
    """摘要：集中管理 Plugin 安全策略、Bridge 分发与 mock 页面。

    参数：
        runtime: 当前桌面运行时。
        registry: 宿主内置的 mock Plugin 注册表。
    """

    _LOW_RISK_PERMISSIONS: ClassVar[frozenset[str]] = frozenset({"memory_read", "memory_toggle"})

    def __init__(self, runtime: DesktopRuntime, registry: dict[str, dict[str, Any]]) -> None:
        self._runtime = runtime
        self._registry = registry
        self._sessions: dict[str, PluginRuntimeSession] = {}
        self._schemas = {
            "memory.read": CapabilitySchema(
                capability="memory.read",
                required_permission="memory_read",
                risk_level="low",
                validator=self._validate_memory_read,
            ),
            "memory.toggle": CapabilitySchema(
                capability="memory.toggle",
                required_permission="memory_toggle",
                risk_level="low",
                validator=self._validate_memory_toggle,
            ),
            "skill.call": CapabilitySchema(
                capability="skill.call",
                required_permission="call_skill",
                risk_level="high",
                validator=self._validate_skill_call,
            ),
        }

    def list_plugins(self) -> list[dict[str, Any]]:
        """摘要：返回可展示的 Plugin 清单。"""
        items: list[dict[str, Any]] = []
        for plugin_id, item in self._registry.items():
            manifest = self._parse_manifest(plugin_id, item.get("manifest", {}))
            items.append(
                {
                    "plugin_id": manifest.plugin_id,
                    "version": manifest.version,
                    "description": manifest.description,
                    "permissions": list(manifest.permissions),
                    "capabilities": list(manifest.capabilities),
                }
            )
        return items

    def create_session(self, plugin_id: str) -> dict[str, Any]:
        """摘要：按 UI 挂载生命周期创建新的 Plugin 安全会话。"""
        manifest = self._require_manifest(plugin_id)
        session_id = secrets.token_hex(8)
        session_token = secrets.token_hex(16)
        session = PluginRuntimeSession(
            session_id=session_id,
            session_token=session_token,
            plugin_id=plugin_id,
            capabilities=manifest.capabilities,
            permissions=manifest.permissions,
        )
        session.record("session_created", permissions=list(manifest.permissions))
        self._sessions[session_id] = session
        return {
            "plugin_id": plugin_id,
            "session_id": session_id,
            "session_token": session_token,
            "sandbox": "allow-scripts",
            "frame_path": f"/api/plugins/frame/{plugin_id}",
        }

    def destroy_session(self, session_id: str) -> None:
        """摘要：销毁 Plugin 会话并撤销后续消息权限。"""
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.active = False
        session.record("session_destroyed")

    def frame_html(self, plugin_id: str) -> str:
        """摘要：返回 mock Plugin iframe HTML。"""
        if plugin_id not in self._registry:
            raise PluginSecurityError(f"未知 plugin: {plugin_id}")
        return str(self._registry[plugin_id]["frame_html"])

    def handle_bridge_message(self, raw: dict[str, Any]) -> dict[str, Any]:
        """摘要：校验并处理来自 iframe 的 Bridge 请求。

        参数：
            raw: iframe 通过 ``postMessage`` 发送的原始消息。

        返回：
            可回传给 iframe 的结构化响应。

        Raises:
            PluginSecurityError: 当会话、权限或 schema 校验失败时抛出。
        """
        self._validate_envelope(raw)
        session_id = str(raw["session_id"])
        plugin_id = str(raw["plugin_id"])
        request_id = str(raw["request_id"])
        capability = str(raw["capability"])
        payload = dict(raw.get("payload") or {})
        token = str(raw["session_token"])
        session = self._require_session(session_id, plugin_id, token)
        self._authorize(session, capability, payload)
        data = self._dispatch(session, capability, payload)
        session.record("bridge_allowed", capability=capability, request_id=request_id)
        return {
            "type": "plugin.bridge.response",
            "plugin_id": plugin_id,
            "session_id": session_id,
            "request_id": request_id,
            "ok": True,
            "capability": capability,
            "data": data,
        }

    def _dispatch(self, session: PluginRuntimeSession, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        if capability == "memory.read":
            limit = min(int(payload.get("limit", 5)), 10)
            rows = MemoryLifecycleManager.list_memory_rows(
                self._runtime.orchestrator.conn,
                limit=limit,
                offset=0,
                order_by="modified_at DESC, id DESC",
            )
            return {"items": rows}
        if capability == "memory.toggle":
            enabled = bool(payload["enabled"])
            self._runtime.memory_on = enabled
            session.record("memory_toggled", enabled=enabled)
            return {"memory_on": enabled}
        if capability == "skill.call":
            raise PluginSecurityError("High-risk capability requires A3 consent in mock host")
        raise PluginSecurityError(f"Unsupported capability: {capability}")

    def _authorize(self, session: PluginRuntimeSession, capability: str, payload: dict[str, Any]) -> None:
        schema = self._schemas.get(capability)
        if schema is None:
            raise PluginSecurityError(f"Capability is not registered: {capability}")
        if capability not in session.capabilities:
            session.record("bridge_denied", capability=capability, reason="capability_not_granted")
            raise PluginSecurityError(f"Capability is not granted: {capability}")
        if schema.required_permission not in session.permissions:
            session.record("bridge_denied", capability=capability, reason="permission_missing")
            raise PluginSecurityError(f"Missing manifest permission: {schema.required_permission}")
        if schema.risk_level != "low":
            session.record("bridge_denied", capability=capability, reason="high_risk_capability")
            raise PluginSecurityError(f"High-risk capability is blocked: {capability}")
        schema.validator(payload)

    def _parse_manifest(self, plugin_id: str, raw: dict[str, Any]) -> PluginManifest:
        if raw.get("type") != "plugin":
            raise PluginSecurityError(f"{plugin_id} manifest.type must be plugin")
        permissions = tuple(str(item) for item in raw.get("permissions", []))
        capabilities = tuple(str(item) for item in raw.get("capabilities", []))
        for permission in permissions:
            if permission not in self._LOW_RISK_PERMISSIONS and permission != "call_skill":
                raise PluginSecurityError(f"{plugin_id} declared unknown permission: {permission}")
        return PluginManifest(
            plugin_id=plugin_id,
            version=str(raw.get("version", "0.0.0")),
            description=str(raw.get("description", "")),
            permissions=permissions,
            capabilities=capabilities,
        )

    def _require_manifest(self, plugin_id: str) -> PluginManifest:
        item = self._registry.get(plugin_id)
        if item is None:
            raise PluginSecurityError(f"Unknown plugin: {plugin_id}")
        return self._parse_manifest(plugin_id, dict(item.get("manifest", {})))

    def _require_session(self, session_id: str, plugin_id: str, token: str) -> PluginRuntimeSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise PluginSecurityError("Plugin session does not exist")
        if not session.active:
            raise PluginSecurityError("Plugin session has been destroyed")
        if session.plugin_id != plugin_id:
            raise PluginSecurityError("plugin_id does not match session")
        if session.session_token != token:
            raise PluginSecurityError("session_token validation failed")
        return session

    def _validate_envelope(self, raw: dict[str, Any]) -> None:
        required = {"type", "plugin_id", "session_id", "session_token", "request_id", "capability", "payload"}
        missing = [name for name in required if name not in raw]
        if missing:
            raise PluginSecurityError(f"Bridge message missing fields: {', '.join(missing)}")
        if raw.get("type") != "plugin.bridge.request":
            raise PluginSecurityError("Bridge message type is invalid")
        for field_name in ("plugin_id", "session_id", "session_token", "request_id", "capability"):
            value = raw.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise PluginSecurityError(f"{field_name} must be a non-empty string")
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            raise PluginSecurityError("payload must be an object")

    @staticmethod
    def _validate_memory_read(payload: dict[str, Any]) -> None:
        limit = payload.get("limit", 5)
        if not isinstance(limit, int):
            raise PluginSecurityError("memory.read limit must be an integer")
        if limit < 1 or limit > 10:
            raise PluginSecurityError("memory.read limit is out of allowed range")

    @staticmethod
    def _validate_memory_toggle(payload: dict[str, Any]) -> None:
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise PluginSecurityError("memory.toggle enabled must be a boolean")

    @staticmethod
    def _validate_skill_call(payload: dict[str, Any]) -> None:
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PluginSecurityError("skill.call name must be a non-empty string")
