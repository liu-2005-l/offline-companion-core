"""invoker：Tool 执行与 Consent 暂停恢复。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from offline_companion.core.plan_orchestrator import ConsentRequest
from offline_companion.shared.types import PrivacyMode, PurposeType, ToolManifest, ToolResult
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway

from .errors import ToolBlockedError
from .registry import ToolRegistry


@dataclass(frozen=True)
class _PendingToolAction:
    """摘要：待用户 Consent 后恢复的 Tool 操作。"""

    action: str
    tool_id: str
    params: dict[str, object]
    session_id: str
    privacy_mode: PrivacyMode
    started_at: float


@dataclass
class ToolInvoker:
    """摘要：Tool 执行器。

    Builtin Tool 直接调用 handler；
    External Tool 通过 localhost HTTP API 转发；
    遇到 ask 权限时返回 requires_consent，由调用层恢复。
    """

    registry: ToolRegistry
    consent_gateway: UIHostConsentGateway | None = None
    pending_actions: dict[str, _PendingToolAction] = field(default_factory=dict)

    def execute(
        self,
        tool_id: str,
        params: dict[str, object],
        *,
        session_id: str,
        privacy_mode: PrivacyMode,
    ) -> ToolResult:
        """摘要：执行一个 Tool，必要时返回待 Consent 的挂起结果。"""
        started_at = time.perf_counter()
        try:
            manifest = self.registry.require_manifest(tool_id)
        except KeyError as exc:
            return self._error_result(
                tool_id,
                code="tool_not_found",
                message=str(exc),
                started_at=started_at,
                session_id=session_id,
            )
        permission = self.registry.resolve_permission(tool_id, privacy_mode=privacy_mode)
        if permission == "deny":
            return self._denied_result(
                manifest,
                started_at=started_at,
                reason="permission_denied",
                session_id=session_id,
            )
        if permission == "ask":
            return self._request_consent(
                action="execute",
                manifest=manifest,
                params=params,
                session_id=session_id,
                privacy_mode=privacy_mode,
                started_at=started_at,
                purpose_type=PurposeType.TOOL_USE,
            )
        return self._execute_allowed(manifest, params=params, session_id=session_id, started_at=started_at)

    def enable_external(
        self,
        tool_id: str,
        *,
        session_id: str,
        privacy_mode: PrivacyMode,
    ) -> ToolResult:
        """摘要：显式启用 external Tool，必要时先走 Consent。"""
        started_at = time.perf_counter()
        try:
            manifest = self.registry.require_manifest(tool_id)
        except KeyError as exc:
            return self._error_result(
                tool_id,
                code="tool_not_found",
                message=str(exc),
                started_at=started_at,
                session_id=session_id,
            )
        if manifest.tool_type != "external":
            return self._error_result(
                tool_id,
                code="tool_not_external",
                message="only external tools support enable flow",
                started_at=started_at,
                session_id=session_id,
            )
        if manifest.enabled:
            return self._completed_result(
                manifest,
                result={"enabled": True},
                started_at=started_at,
                audit_record=self._audit_record(
                    manifest,
                    status="completed",
                    session_id=session_id,
                    params={},
                    extra={"action": "enable_external", "enabled": True},
                ),
            )
        return self._request_consent(
            action="enable_external",
            manifest=manifest,
            params={},
            session_id=session_id,
            privacy_mode=privacy_mode,
            started_at=started_at,
            purpose_type=PurposeType.TOOL_EXTERNAL_ENABLE,
        )

    def resume(self, consent_request_id: str, *, allowed: bool) -> ToolResult:
        """摘要：恢复一条等待 Consent 的 Tool 操作。"""
        pending = self.pending_actions.pop(consent_request_id, None)
        if pending is None:
            raise KeyError(f"unknown tool consent_request_id: {consent_request_id}")
        if self.consent_gateway is not None:
            consent = self.consent_gateway.get_pending(consent_request_id)
            if consent is not None and not consent.decided:
                self.consent_gateway.decide(consent_request_id, allowed)
        manifest = self.registry.require_manifest(pending.tool_id)
        if not allowed:
            return ToolResult(
                tool_id=pending.tool_id,
                status="consent_rejected",
                result=None,
                error={"code": "consent_rejected", "message": "user rejected tool consent"},
                consent_request_id=None,
                audit_record=self._audit_record(
                    manifest,
                    status="consent_rejected",
                    session_id=pending.session_id,
                    params=pending.params,
                    extra={"action": pending.action},
                ),
                duration_ms=(time.perf_counter() - pending.started_at) * 1000.0,
            )
        if pending.action == "enable_external":
            self.registry.set_external_enabled(pending.tool_id, True)
            enabled_manifest = self.registry.require_manifest(pending.tool_id)
            return self._completed_result(
                enabled_manifest,
                result={"enabled": True},
                started_at=pending.started_at,
                audit_record=self._audit_record(
                    enabled_manifest,
                    status="completed",
                    session_id=pending.session_id,
                    params={},
                    extra={"action": "enable_external", "enabled": True},
                ),
            )
        return self._execute_allowed(
            manifest,
            params=pending.params,
            session_id=pending.session_id,
            started_at=pending.started_at,
        )

    def _request_consent(
        self,
        *,
        action: str,
        manifest: ToolManifest,
        params: dict[str, object],
        session_id: str,
        privacy_mode: PrivacyMode,
        started_at: float,
        purpose_type: PurposeType,
    ) -> ToolResult:
        request = ConsentRequest(
            plan_id=session_id,
            step_id=f"tool:{manifest.tool_id}",
            skill_id=f"tool_{manifest.tool_id}",
            operation=action,
            purpose_type=purpose_type,
            risk_level="medium",
            impact_scope="single_turn",
            source="tool_invoker",
            metadata={
                "purpose_type": purpose_type.value,
                "tool_id": manifest.tool_id,
                "scope": manifest.scope,
                "permission": manifest.permission,
                "params_summary": {key: str(value)[:120] for key, value in params.items()},
                "reason": f"tool permission={manifest.permission}",
                "privacy_mode": privacy_mode.value,
            },
        )
        if self.consent_gateway is None:
            return self._denied_result(
                manifest,
                started_at=started_at,
                reason="consent_infrastructure_unavailable",
                session_id=session_id,
            )
        allowed = self.consent_gateway.submit(request)
        artifact = self.consent_gateway.last_artifact or {}
        request_id = str(artifact.get("request_id") or "")
        pending = self.consent_gateway.get_pending(request_id or None)
        if request_id and pending is not None and not pending.decided:
            self.pending_actions[request_id] = _PendingToolAction(
                action=action,
                tool_id=manifest.tool_id,
                params=dict(params),
                session_id=session_id,
                privacy_mode=privacy_mode,
                started_at=started_at,
            )
            return ToolResult(
                tool_id=manifest.tool_id,
                status="requires_consent",
                result=None,
                error=None,
                consent_request_id=request_id,
                audit_record=self._audit_record(
                    manifest,
                    status="requires_consent",
                    session_id=session_id,
                    params=params,
                    extra={"action": action, "purpose_type": purpose_type.value},
                ),
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
        if not allowed:
            return ToolResult(
                tool_id=manifest.tool_id,
                status="consent_rejected",
                result=None,
                error={"code": "consent_rejected", "message": "user rejected tool consent"},
                consent_request_id=None,
                audit_record=self._audit_record(
                    manifest,
                    status="consent_rejected",
                    session_id=session_id,
                    params=params,
                    extra={"action": action, "purpose_type": purpose_type.value},
                ),
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
        if action == "enable_external":
            self.registry.set_external_enabled(manifest.tool_id, True)
            manifest = self.registry.require_manifest(manifest.tool_id)
            return self._completed_result(
                manifest,
                result={"enabled": True},
                started_at=started_at,
                audit_record=self._audit_record(
                    manifest,
                    status="completed",
                    session_id=session_id,
                    params={},
                    extra={"action": "enable_external", "enabled": True},
                ),
            )
        return self._execute_allowed(manifest, params=params, session_id=session_id, started_at=started_at)

    def _execute_allowed(
        self,
        manifest: ToolManifest,
        *,
        params: dict[str, object],
        session_id: str,
        started_at: float,
    ) -> ToolResult:
        audit = self._audit_record(manifest, status="completed", session_id=session_id, params=params)
        try:
            if manifest.tool_type == "builtin":
                handler = self.registry.get_builtin_handler(manifest.tool_id)
                safe_params = dict(params)
                safe_params.pop("session_id", None)
                if self.registry.injects_session_id(manifest.tool_id):
                    result = handler(session_id=session_id, **safe_params)
                else:
                    result = handler(**safe_params)
            else:
                result = self._call_external(manifest, params)
        except ToolBlockedError as exc:
            return ToolResult(
                tool_id=manifest.tool_id,
                status="blocked",
                result=exc.data,
                error={"code": "hard_gate_blocked", "message": str(exc)},
                consent_request_id=None,
                audit_record={**audit, "status": "blocked", "reason": str(exc)},
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_id=manifest.tool_id,
                status="error",
                result=None,
                error={"code": "tool_execution_failed", "message": str(exc)},
                consent_request_id=None,
                audit_record={**audit, "status": "error", "error": str(exc)},
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
        return self._completed_result(manifest, result=result, started_at=started_at, audit_record=audit)

    def _call_external(self, manifest: ToolManifest, params: dict[str, object]) -> dict[str, object]:
        """摘要：通过 localhost HTTP API 执行 external Tool。"""
        if not manifest.endpoint:
            raise ValueError("external tool missing endpoint")
        payload = json.dumps(params, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            manifest.endpoint,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"external tool request failed: {exc}") from exc
        if not raw.strip():
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError("external tool response must be a JSON object")
        return {str(key): value for key, value in parsed.items()}

    def _completed_result(
        self,
        manifest: ToolManifest,
        *,
        result: dict[str, object],
        started_at: float,
        audit_record: dict[str, object],
    ) -> ToolResult:
        return ToolResult(
            tool_id=manifest.tool_id,
            status="completed",
            result=result,
            error=None,
            consent_request_id=None,
            audit_record=audit_record,
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
        )

    def _denied_result(self, manifest: ToolManifest, *, started_at: float, reason: str, session_id: str) -> ToolResult:
        return ToolResult(
            tool_id=manifest.tool_id,
            status="denied",
            result=None,
            error={"code": "tool_permission_denied", "message": reason},
            consent_request_id=None,
            audit_record=self._audit_record(
                manifest,
                status="denied",
                session_id=session_id,
                params={},
                extra={"reason": reason},
            ),
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
        )

    def _error_result(self, tool_id: str, *, code: str, message: str, started_at: float, session_id: str) -> ToolResult:
        return ToolResult(
            tool_id=tool_id,
            status="error",
            result=None,
            error={"code": code, "message": message},
            consent_request_id=None,
            audit_record={
                "tool_id": tool_id,
                "status": "error",
                "session_id": session_id,
                "error": {"code": code, "message": message},
            },
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
        )

    def _audit_record(
        self,
        manifest: ToolManifest,
        *,
        status: str,
        session_id: str,
        params: dict[str, object],
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        record: dict[str, object] = {
            "tool_id": manifest.tool_id,
            "tool_type": manifest.tool_type,
            "scope": manifest.scope,
            "permission": manifest.permission,
            "status": status,
            "session_id": session_id,
            "params_summary": {key: str(value)[:120] for key, value in params.items()},
            "audit_only": manifest.audit_only,
        }
        if extra:
            record.update(extra)
        return record
