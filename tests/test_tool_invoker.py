from __future__ import annotations

from pathlib import Path

from offline_companion.core.tools.datetime_tool import datetime_now
from offline_companion.core.tools.file_read_tool import file_read
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.types import PrivacyMode, ToolManifest
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.tool_registry.invoker import ToolInvoker
from offline_companion.shell.tool_registry.registry import ToolRegistry


def _manifest(*, tool_id: str, permission: str, scope: str, handler_function: str) -> ToolManifest:
    return ToolManifest(
        tool_id=tool_id,
        display_name=tool_id,
        description=tool_id,
        tool_type="builtin",
        permission=permission,  # type: ignore[arg-type]
        scope=scope,
        params_schema={"type": "object"},
        return_schema={"type": "object"},
        handler_module="test",
        handler_function=handler_function,
        external_config=None,
        version="0.1.0",
    )


def test_invoker_executes_allow_builtin() -> None:
    registry = ToolRegistry()
    registry.register_builtin(_manifest(tool_id="datetime_now", permission="allow", scope="datetime", handler_function="datetime_now"), datetime_now)
    invoker = ToolInvoker(registry)

    result = invoker.execute("datetime_now", {}, session_id="s1", privacy_mode=PrivacyMode.LOCAL_ONLY)

    assert result.status == "completed"
    assert result.result is not None
    assert "iso_utc" in result.result


def test_invoker_returns_pending_for_ask_builtin_and_can_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OFFLINE_COMPANION_DATA_DIR", str(tmp_path))
    allowed_file = tmp_path / "note.txt"
    allowed_file.write_text("hello", encoding="utf-8")
    registry = ToolRegistry()
    registry.register_builtin(_manifest(tool_id="file_read", permission="ask", scope="file_read", handler_function="file_read"), file_read)
    gateway = UIHostConsentGateway()
    invoker = ToolInvoker(registry, consent_gateway=gateway)

    pending = invoker.execute(
        "file_read",
        {"path": str(allowed_file)},
        session_id="s1",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )

    assert pending.status == "requires_consent"
    assert pending.consent_request_id is not None

    resumed = invoker.resume(pending.consent_request_id, allowed=True)

    assert resumed.status == "completed"
    assert resumed.result == {"path": str(allowed_file.resolve()), "content": "hello"}


def test_invoker_enable_external_returns_pending_and_sets_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "tools_external.yaml"
    config_path.write_text(
        """
tools:
  - tool_id: web_search
    display_name: Web Search
    description: Search the web
    scope: network_egress
    permission: ask
    endpoint: http://localhost:8080/tool/web_search
    params_schema: {type: object}
    return_schema: {type: object}
    version: 0.1.0
    enabled: false
""".strip(),
        encoding="utf-8",
    )
    registry = ToolRegistry()
    registry.load_external(config_path)
    invoker = ToolInvoker(registry, consent_gateway=UIHostConsentGateway())

    pending = invoker.enable_external("web_search", session_id="s1", privacy_mode=PrivacyMode.AUTO_ROUTE_CLOUD)

    assert pending.status == "requires_consent"
    assert pending.consent_request_id is not None

    resumed = invoker.resume(pending.consent_request_id, allowed=True)

    assert resumed.status == "completed"
    assert resumed.result == {"enabled": True}
    assert registry.require_manifest("web_search").enabled is True


def test_invoker_denies_disabled_external(tmp_path: Path) -> None:
    config_path = tmp_path / "tools_external.yaml"
    config_path.write_text(
        """
tools:
  - tool_id: web_search
    display_name: Web Search
    description: Search the web
    scope: network_egress
    permission: ask
    endpoint: http://localhost:8080/tool/web_search
    params_schema: {type: object}
    return_schema: {type: object}
    version: 0.1.0
    enabled: false
""".strip(),
        encoding="utf-8",
    )
    registry = ToolRegistry()
    registry.load_external(config_path)
    invoker = ToolInvoker(registry)

    result = invoker.execute("web_search", {"query": "news"}, session_id="s1", privacy_mode=PrivacyMode.AUTO_ROUTE_CLOUD)

    assert result.status == "denied"
    assert result.audit_record["session_id"] == "s1"


def test_invoker_resume_rejected_returns_consent_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OFFLINE_COMPANION_DATA_DIR", str(tmp_path))
    allowed_file = tmp_path / "note.txt"
    allowed_file.write_text("hello", encoding="utf-8")
    registry = ToolRegistry()
    registry.register_builtin(
        _manifest(tool_id="file_read", permission="ask", scope="file_read", handler_function="file_read"),
        file_read,
    )
    gateway = UIHostConsentGateway()
    invoker = ToolInvoker(registry, consent_gateway=gateway)

    pending = invoker.execute(
        "file_read",
        {"path": str(allowed_file)},
        session_id="s1",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )

    rejected = invoker.resume(pending.consent_request_id, allowed=False)  # type: ignore[arg-type]

    assert rejected.status == "consent_rejected"
    assert rejected.error == {"code": "consent_rejected", "message": "user rejected tool consent"}
    assert rejected.audit_record["status"] == "consent_rejected"
    assert rejected.audit_record["session_id"] == "s1"


def test_invoker_without_gateway_fails_safe_on_ask(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OFFLINE_COMPANION_DATA_DIR", str(tmp_path))
    allowed_file = tmp_path / "note.txt"
    allowed_file.write_text("hello", encoding="utf-8")
    registry = ToolRegistry()
    registry.register_builtin(
        _manifest(tool_id="file_read", permission="ask", scope="file_read", handler_function="file_read"),
        file_read,
    )
    invoker = ToolInvoker(registry, consent_gateway=None)

    result = invoker.execute(
        "file_read",
        {"path": str(allowed_file)},
        session_id="s1",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )

    assert result.status == "denied"
    assert result.error == {"code": "tool_permission_denied", "message": "consent_infrastructure_unavailable"}
    assert result.audit_record["session_id"] == "s1"


def test_tool_execution_does_not_write_memory(tmp_path: Path) -> None:
    conn = connect(tmp_path / "companion.db")
    new_session(conn, "s1", "default", title=None)
    before = conn.execute("SELECT COUNT(*) AS c FROM memory_chunks;").fetchone()["c"]
    registry = ToolRegistry()
    registry.register_builtin(_manifest(tool_id="datetime_now", permission="allow", scope="datetime", handler_function="datetime_now"), datetime_now)
    invoker = ToolInvoker(registry)

    result = invoker.execute("datetime_now", {}, session_id="s1", privacy_mode=PrivacyMode.LOCAL_ONLY)

    after = conn.execute("SELECT COUNT(*) AS c FROM memory_chunks;").fetchone()["c"]
    assert result.status == "completed"
    assert before == after
