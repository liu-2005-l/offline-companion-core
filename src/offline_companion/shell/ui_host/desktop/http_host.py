"""摘要：桌面壳内嵌 127.0.0.1 HTTP 宿主。"""

from __future__ import annotations

import json
import logging
import secrets
import socket
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import offline_companion.shell.ui_host.desktop as _desktop_pkg
from offline_companion import __version__
from offline_companion.core.memory_lifecycle.fts_ops import (
    count_memory_rows,
    invalidate_memory_chunk,
    restore_memory_chunk,
    update_memory_chunk,
)
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.persona_session.persona_loader import (
    load_persona_file,
    resolved_companion_display_name,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.plan_orchestrator import ConsentRequest
from offline_companion.runtime.inference_backend import create_llama_backend
from offline_companion.runtime.storage_index.engine import clear_session_messages
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.shared.types import PrivacyMode
from offline_companion.shell.skill_manager.registry import load_installed_manifests
from offline_companion.shell.ui_host.desktop.privacy_socket_guard import apply_privacy_socket_guard
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shell.ui_host.model_registry import (
    discover_models,
    runtime_config_from_descriptor,
)
from offline_companion.shell.ui_host.plugin_loader import (
    PluginSecurityGateway,
    build_mock_plugin_registry,
)
from offline_companion.shell.ui_host.turn_payload import (
    process_chat_message,
    process_chat_message_stream,
    turn_result_to_payload,
)
from offline_companion.storage.extension_repo import init_extension_status, save_extension_status
from offline_companion.storage.persona_repo import (
    activate_persona as activate_persisted_persona,
)
from offline_companion.storage.persona_repo import (
    active_persona,
    list_personas,
)
from offline_companion.storage.plan_repo import delete_plan, get_plan, save_plan, update_plan
from offline_companion.storage.settings_store import load_settings, update_settings

_ALLOWED_HOST = "127.0.0.1"
logger = logging.getLogger(__name__)


def _static_dir() -> Path:
    return Path(_desktop_pkg.__file__).resolve().parent / "static"


def _pick_port() -> int:
    """摘要：选择本机空闲端口。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((_ALLOWED_HOST, 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@dataclass
class DesktopHttpServer:
    """摘要：内嵌 Flask 服务句柄。"""

    port: int
    thread: threading.Thread


def create_desktop_app(runtime: DesktopRuntime):
    """摘要：创建桌面壳 Flask 应用。"""
    try:
        from flask import Flask, Response, jsonify, request, send_from_directory
    except ImportError as exc:
        raise ImportError("桌面壳 HTTP 需要 Flask，请安装 `pip install -e \".[webui,desktop]\"`") from exc

    static = _static_dir()
    app = Flask(__name__, static_folder=str(static), static_url_path="")
    plugin_gateway = PluginSecurityGateway(runtime, build_mock_plugin_registry())
    settings_state: dict[str, Any] = load_settings(runtime.paths.root)
    persisted_privacy_mode = _parse_privacy_mode(settings_state.get("privacy_mode"))
    if persisted_privacy_mode is not None:
        runtime.privacy_mode = persisted_privacy_mode
        runtime.orchestrator.privacy_mode = persisted_privacy_mode
    runtime.memory_on = bool(settings_state.get("memory_enabled", runtime.memory_on))
    runtime.improve_plan_enabled = bool(settings_state.get("improve_plan_enabled", False))
    model_state: dict[str, Any] = {"auto": bool(settings_state.get("auto_router_enabled", False))}
    model_lock = threading.Lock()
    extension_state: dict[str, bool] = init_extension_status(runtime.paths.root, runtime.paths.db_path)
    persisted_persona = active_persona(runtime.orchestrator.conn)
    if persisted_persona is not None:
        runtime.orchestrator.session_core = PersonaSessionCore(persisted_persona)
        runtime.persona_name = resolved_companion_display_name(persisted_persona)
    runtime.logged_in = bool(getattr(runtime, "logged_in", False))
    runtime.account_name = str(getattr(runtime, "account_name", "local-user"))
    runtime.improve_plan_enabled = bool(getattr(runtime, "improve_plan_enabled", False))
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @app.get("/")
    def index():
        return send_from_directory(static, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(static, "favicon.ico")

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        request_id = uuid.uuid4().hex
        log_dir = runtime.paths.root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"http_500_{request_id}.log"
        log_path.write_text(
            "".join(
                [
                    f"request_id={request_id}\n",
                    f"path={request.path}\n",
                    f"method={request.method}\n\n",
                    "".join(traceback.format_exception(error)),
                ]
            ),
            encoding="utf-8",
        )
        return jsonify({"error": "internal_error", "request_id": request_id}), 500

    @app.get("/api/status")
    def status():
        return _json_response(
            jsonify,
            {
                "app_version": __version__,
                "memory_on": runtime.memory_on,
                "session_id": runtime.session_id,
                "persona_id": runtime.orchestrator.session_core.persona.persona_id,
                "persona_name": runtime.persona_name,
                "privacy_mode": runtime.privacy_mode.value,
                "model_label": runtime.model_label,
                "logged_in": bool(getattr(runtime, "logged_in", False)),
                "socket_guard_enabled": bool(getattr(runtime, "socket_guard_enabled", False)),
            },
        )

    @app.get("/api/about")
    def about():
        return _json_response(
            jsonify,
            {
                "app_name": "Offline Companion",
                "app_version": __version__,
                "model_label": runtime.model_label,
                "architecture": "PyInstaller + llama-server sidecar",
                "license": "BSD-2-Clause",
                "repository": "offline-companion-core",
            },
        )

    @app.get("/api/settings")
    def settings():
        return _json_response(
            jsonify,
            {
                "settings": load_settings(runtime.paths.root),
                "data_root": str(runtime.paths.root),
                "settings_path": str(runtime.paths.root / "settings.json"),
            },
        )

    @app.post("/api/settings")
    def set_settings():
        data = request.get_json(silent=True) or {}
        patch = data.get("settings") if isinstance(data.get("settings"), dict) else data
        if not isinstance(patch, dict):
            return _json_response(jsonify, {"error": "invalid_settings"}, status=400)
        saved = update_settings(runtime.paths.root, patch)
        mode = _parse_privacy_mode(saved.get("privacy_mode"))
        if mode is not None:
            runtime.privacy_mode = mode
            runtime.orchestrator.privacy_mode = mode
        runtime.improve_plan_enabled = bool(saved.get("improve_plan_enabled", False))
        runtime.memory_on = bool(saved.get("memory_enabled", runtime.memory_on))
        model_state["auto"] = bool(saved.get("auto_router_enabled", model_state["auto"]))
        return _json_response(
            jsonify,
            {
                "ok": True,
                "settings": saved,
                "data_root": str(runtime.paths.root),
                "settings_path": str(runtime.paths.root / "settings.json"),
            },
        )

    @app.get("/api/settings/apply-trace")
    def settings_apply_trace():
        path = runtime.paths.root / "settings_apply_trace.json"
        if not path.is_file():
            return _json_response(jsonify, {"trace": None, "path": str(path)})
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"error": "invalid_trace_json"}
        return _json_response(jsonify, {"trace": payload, "path": str(path)})

    @app.post("/api/settings/apply-trace")
    def save_settings_apply_trace():
        data = request.get_json(silent=True) or {}
        path = runtime.paths.root / "settings_apply_trace.json"
        path.write_text(json.dumps(_json_safe(data), ensure_ascii=False, indent=2), encoding="utf-8")
        return _json_response(jsonify, {"ok": True, "path": str(path)})

    @app.get("/api/settings/dom-snapshot")
    def settings_dom_snapshot():
        path = runtime.paths.root / "settings_dom_snapshot.json"
        if not path.is_file():
            return _json_response(jsonify, {"snapshot": None, "path": str(path)})
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"error": "invalid_snapshot_json"}
        return _json_response(jsonify, {"snapshot": payload, "path": str(path)})

    @app.post("/api/settings/dom-snapshot")
    def save_settings_dom_snapshot():
        data = request.get_json(silent=True) or {}
        path = runtime.paths.root / "settings_dom_snapshot.json"
        path.write_text(json.dumps(_json_safe(data), ensure_ascii=False, indent=2), encoding="utf-8")
        return _json_response(jsonify, {"ok": True, "path": str(path)})

    @app.post("/api/memory")
    def set_memory():
        data = request.get_json(silent=True) or {}
        runtime.memory_on = bool(data.get("enabled", True))
        saved = update_settings(runtime.paths.root, {"memory_enabled": runtime.memory_on})
        return _json_response(
            jsonify,
            {"memory_on": runtime.memory_on, "locked": False, "settings": saved},
        )

    @app.post("/api/auth/login")
    def auth_login():
        data = request.get_json(silent=True) or {}
        auth = _ensure_auth_file(runtime.paths.root)
        token = str(data.get("token") or "").strip()
        if not token or not secrets.compare_digest(token, str(auth.get("token") or "")):
            return _json_response(jsonify, {"error": "invalid_token", "logged_in": False}, status=401)
        runtime.logged_in = True
        runtime.account_name = str(auth.get("account_name") or "local-user")
        return _json_response(jsonify, _auth_status_payload(runtime, auth))

    @app.post("/api/auth/logout")
    def auth_logout():
        runtime.logged_in = False
        runtime.improve_plan_enabled = False
        update_settings(runtime.paths.root, {"improve_plan_enabled": False})
        _write_improve_plan_state(runtime.paths.root, {"enabled": False, "last_upload_at": None})
        return _json_response(jsonify, {"logged_in": False, "improve_plan_enabled": False})

    @app.get("/api/auth/status")
    def auth_status():
        auth = _ensure_auth_file(runtime.paths.root)
        return _json_response(jsonify, _auth_status_payload(runtime, auth))

    @app.get("/api/improve-plan")
    def improve_plan_status():
        return _json_response(jsonify, _improve_plan_payload(runtime))

    @app.post("/api/improve-plan")
    def set_improve_plan():
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("enabled", True))
        if enabled and (
            not bool(getattr(runtime, "logged_in", False))
            or runtime.privacy_mode is not PrivacyMode.AUTO_ROUTE_CLOUD
        ):
            return _json_response(
                jsonify,
                {"error": "requires_login_and_cloud", "enabled": bool(getattr(runtime, "improve_plan_enabled", False))},
                status=403,
            )
        runtime.improve_plan_enabled = enabled
        update_settings(runtime.paths.root, {"improve_plan_enabled": enabled})
        state = _read_improve_plan_state(runtime.paths.root)
        state["enabled"] = enabled
        state.setdefault("last_upload_at", None)
        _write_improve_plan_state(runtime.paths.root, state)
        return _json_response(jsonify, _improve_plan_payload(runtime))

    @app.get("/api/sse-test")
    def sse_test():
        def generate():
            for index in range(5):
                yield f"data: {json.dumps({'i': index}, ensure_ascii=False)}\n\n"
                time.sleep(0.3)
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

        return _sse_response(Response, generate())

    @app.post("/api/privacy/mode")
    def set_privacy_mode():
        data = request.get_json(silent=True) or {}
        mode = _parse_privacy_mode(data.get("mode"))
        if mode is None:
            return _json_response(jsonify, {"error": "invalid privacy mode"}, status=400)
        runtime.privacy_mode = mode
        runtime.orchestrator.privacy_mode = mode
        runtime.socket_guard_enabled = apply_privacy_socket_guard(mode is PrivacyMode.LOCAL_ONLY)
        update_settings(runtime.paths.root, {"privacy_mode": mode.value})
        return _json_response(
            jsonify,
            {
                "ok": True,
                "privacy_mode": mode.value,
                "socket_guard_enabled": runtime.socket_guard_enabled,
                "existing_connections": "unchanged",
            },
        )

    @app.post("/api/feedback")
    def feedback():
        data = request.get_json(silent=True) or {}
        item = {
            "created_at": time.time(),
            "session_id": str(data.get("session_id") or runtime.session_id),
            "msg_id": data.get("msg_id"),
            "type": str(data.get("type") or "error"),
            "comment": str(data.get("comment") or ""),
            "privacy_mode": runtime.privacy_mode.value,
            "local_only": runtime.privacy_mode is PrivacyMode.LOCAL_ONLY,
            "queueable": bool(getattr(runtime, "improve_plan_enabled", False))
            and runtime.privacy_mode is PrivacyMode.AUTO_ROUTE_CLOUD
            and bool(getattr(runtime, "logged_in", False)),
        }
        _append_jsonl(runtime.paths.root / "feedback.jsonl", item)
        return _json_response(jsonify, {"ok": True, "queued": runtime.privacy_mode is not PrivacyMode.LOCAL_ONLY})

    @app.post("/api/message/react")
    def message_react():
        data = request.get_json(silent=True) or {}
        emoji = str(data.get("emoji") or "").strip()
        if not emoji:
            return _json_response(jsonify, {"error": "missing emoji"}, status=400)
        session_id = str(data.get("session_id") or runtime.session_id)
        message_id = _resolve_message_id(runtime.orchestrator.conn, session_id, data.get("msg_id"))
        if message_id is None:
            return _json_response(jsonify, {"error": "message not found"}, status=404)
        meta = _message_meta(runtime.orchestrator.conn, message_id)
        reactions = meta.setdefault("reactions", [])
        if isinstance(reactions, list):
            reactions.append({"emoji": emoji, "created_at": time.time()})
        runtime.orchestrator.conn.execute(
            "UPDATE messages SET meta_json = ? WHERE id = ?;",
            (json.dumps(meta, ensure_ascii=False), message_id),
        )
        return _json_response(jsonify, {"ok": True, "msg_id": message_id, "reactions": reactions})

    @app.get("/api/personas")
    def personas():
        items = list_personas(runtime.orchestrator.conn)
        return _json_response(jsonify, {"items": items, "total": len(items)})

    @app.post("/api/personas/<persona_id>/activate")
    def activate_persona(persona_id: str):
        persona = activate_persisted_persona(runtime.orchestrator.conn, persona_id)
        if persona is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        runtime.orchestrator.session_core = PersonaSessionCore(persona)
        runtime.persona_name = resolved_companion_display_name(persona)
        item = next(item for item in list_personas(runtime.orchestrator.conn) if item["id"] == persona_id)
        return _json_response(jsonify, {"ok": True, "persona": item})

    @app.get("/api/models")
    def models():
        items = [_model_payload(model, runtime, model_state) for model in discover_models(data_root_override=runtime.paths.root)]
        if not items and runtime.model_label:
            items.append(
                {
                    "id": runtime.model_label,
                    "name": runtime.model_label,
                    "type": "local",
                    "locked": False,
                    "enabled": True,
                    "active": True,
                    "status": "ready",
                    "meta": {"source": "runtime", "size": None, "ram": None},
                }
            )
        return _json_response(jsonify, {"items": items, "auto": bool(model_state["auto"]), "total": len(items)})

    @app.post("/api/models/<model_id>/activate")
    def activate_model(model_id: str):
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("enabled", True))
        model_state[f"enabled:{model_id}"] = enabled
        if not enabled:
            return _json_response(jsonify, {"ok": True, "active_model_id": model_state.get("active"), "enabled": False})
        if not model_lock.acquire(blocking=False):
            return _json_response(jsonify, {"error": "model_loading"}, status=409)
        try:
            model = _find_model_descriptor(model_id, runtime)
            if model is None:
                if model_id == runtime.model_label:
                    model_state["active"] = model_id
                    return _json_response(
                        jsonify,
                        {"ok": True, "active_model_id": model_state.get("active"), "enabled": True, "reloaded": False},
                    )
                return _json_response(jsonify, {"error": "not_found"}, status=404)
            payload = _model_payload(model, runtime, model_state)
            if payload["type"] == "cloud":
                # 切到云端模型时有意保留本地 backend 常驻，便于快速切回本地模型。
                model_state["active"] = model_id
                runtime.model_label = str(data.get("name") or payload["name"])
                return _json_response(
                    jsonify,
                    {
                        "ok": True,
                        "active_model_id": model_state.get("active"),
                        "enabled": True,
                        "reloaded": False,
                        "model": _model_payload(model, runtime, model_state),
                    },
                )
            if not getattr(model, "gguf_path", None):
                return _json_response(jsonify, {"error": "missing_gguf_path"}, status=400)
            try:
                old_backend = runtime.orchestrator.backend
                new_backend = _load_local_model_backend(runtime, model)
            except (InferenceBackendError, OSError, RuntimeError) as exc:
                return _json_response(jsonify, {"error": "model_reload_failed", "detail": str(exc)}, status=500)
            runtime.orchestrator.backend = new_backend
            stop = getattr(old_backend, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    logger.warning("old backend stop failed after model swap", exc_info=True)
            model_state["active"] = model_id
            runtime.model_label = str(data.get("name") or payload["name"])
            return _json_response(
                jsonify,
                {
                    "ok": True,
                    "active_model_id": model_state.get("active"),
                    "enabled": True,
                    "reloaded": True,
                    "model": _model_payload(model, runtime, model_state),
                },
            )
        finally:
            model_lock.release()

    @app.post("/api/models/auto")
    def set_model_auto():
        data = request.get_json(silent=True) or {}
        model_state["auto"] = bool(data.get("enabled", True))
        update_settings(runtime.paths.root, {"auto_router_enabled": bool(model_state["auto"])})
        return _json_response(jsonify, {"ok": True, "auto": bool(model_state["auto"])})

    @app.get("/api/extensions")
    def extensions():
        items = _extension_payloads(plugin_gateway, runtime, extension_state)
        return _json_response(jsonify, {"items": items, "total": len(items)})

    @app.post("/api/extensions/<extension_id>/toggle")
    def toggle_extension(extension_id: str):
        data = request.get_json(silent=True) or {}
        extension_state[extension_id] = bool(data.get("enabled", True))
        save_extension_status(runtime.paths.db_path, extension_id, extension_state[extension_id])
        return _json_response(jsonify, {"ok": True, "id": extension_id, "enabled": extension_state[extension_id]})

    @app.get("/api/plugins")
    def plugins():
        return _json_response(jsonify, {"items": plugin_gateway.list_plugins()})

    @app.post("/api/plugins/session")
    def create_plugin_session():
        data = request.get_json(silent=True) or {}
        try:
            payload = plugin_gateway.create_session(str(data.get("plugin_id", "")))
            return _json_response(jsonify, payload)
        except Exception as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)

    @app.post("/api/plugins/session/<session_id>/destroy")
    def destroy_plugin_session(session_id: str):
        plugin_gateway.destroy_session(session_id)
        return _json_response(jsonify, {"ok": True})

    @app.get("/api/plugins/frame/<plugin_id>")
    def plugin_frame(plugin_id: str):
        try:
            html = plugin_gateway.frame_html(plugin_id)
            return html, 200, {"Content-Type": "text/html; charset=utf-8"}
        except Exception as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=404)

    @app.post("/api/plugins/message")
    def plugin_message():
        data = request.get_json(silent=True) or {}
        try:
            payload = plugin_gateway.handle_bridge_message(data)
            return _json_response(jsonify, payload)
        except Exception as exc:
            return (
                _json_response(
                    jsonify,
                    {
                        "type": "plugin.bridge.response",
                        "plugin_id": str(data.get("plugin_id", "")),
                        "session_id": str(data.get("session_id", "")),
                        "request_id": str(data.get("request_id", "")),
                        "ok": False,
                        "error": str(exc),
                    }
                ),
                403,
            )

    @app.get("/api/memories")
    def memories():
        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            page = 1
        try:
            page_size = max(1, min(100, int(request.args.get("page_size", "15"))))
        except ValueError:
            page_size = 15
        offset = (page - 1) * page_size
        rows = MemoryLifecycleManager.list_memory_rows(
            runtime.orchestrator.conn,
            limit=page_size,
            offset=offset,
            order_by="modified_at DESC, id DESC",
        )
        grouped = MemoryLifecycleManager.memory_reader.build_grouped_view(
            runtime.orchestrator.conn,
            limit=page_size,
            offset=offset,
            order_by="modified_at DESC, id DESC",
        )
        total = count_memory_rows(runtime.orchestrator.conn)
        return _json_response(
            jsonify,
            {
                "items": rows,
                "grouped": grouped,
                "page": page,
                "page_size": page_size,
                "total": int(total),
            },
        )

    @app.post("/api/memories")
    def create_memory():
        data = request.get_json(silent=True) or {}
        body = str(data.get("content") or data.get("body") or "").strip()
        if not body:
            return _json_response(jsonify, {"error": "missing content"}, status=400)
        tags = data.get("tags")
        if not isinstance(tags, list):
            tags = []
        source = str(data.get("source") or "manual").strip() or "manual"
        meta = {
            "content": body,
            "memory_type": str(data.get("memory_type") or "fact"),
            "status": str(data.get("status") or "active"),
            "source": source,
            "msg_id": data.get("msg_id"),
            "tags": tags,
            "metadata": {
                "source": source,
                "msg_id": data.get("msg_id"),
                "tags": tags,
            },
        }
        memory_id = MemoryLifecycleManager.add_memory_chunk(
            runtime.orchestrator.conn,
            body,
            session_id=runtime.session_id,
            source=source,
            meta=meta,
        )
        item = _memory_row(runtime.orchestrator.conn, memory_id)
        return _json_response(jsonify, {"ok": True, "item": item}, status=201)

    @app.patch("/api/memories/<int:memory_id>")
    def patch_memory(memory_id: int):
        data = request.get_json(silent=True) or {}
        conn = runtime.orchestrator.conn
        changed = False
        if "content" in data or "body" in data:
            body = str(data.get("content") or data.get("body") or "").strip()
            if not body:
                return _json_response(jsonify, {"error": "empty body"}, status=400)
            changed = update_memory_chunk(conn, memory_id, body) or changed
        if "status" in data:
            status_value = str(data.get("status") or "").strip().lower()
            if status_value == "active":
                changed = restore_memory_chunk(conn, memory_id) or changed
            elif status_value in {"inactive", "invalid", "cancelled"}:
                changed = invalidate_memory_chunk(conn, memory_id) or changed
            else:
                return _json_response(jsonify, {"error": "invalid status"}, status=400)
        item = _memory_row(conn, memory_id)
        if item is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        return _json_response(jsonify, {"ok": changed, "item": item})

    @app.post("/api/memories/<int:memory_id>/invalidate")
    def invalidate_memory(memory_id: int):
        ok = invalidate_memory_chunk(runtime.orchestrator.conn, memory_id)
        return _json_response(jsonify, {"ok": ok})

    @app.post("/api/memories/<int:memory_id>/restore")
    def restore_memory(memory_id: int):
        ok = restore_memory_chunk(runtime.orchestrator.conn, memory_id)
        return _json_response(jsonify, {"ok": ok})

    @app.post("/api/memories/<int:memory_id>/delete")
    def delete_memory(memory_id: int):
        ok = MemoryLifecycleManager.delete_memory_chunk(runtime.orchestrator.conn, memory_id)
        return _json_response(jsonify, {"ok": ok})

    @app.get("/api/sessions")
    def sessions():
        rows = runtime.orchestrator.conn.execute(
            """
            SELECT
                s.id AS session_id,
                s.title AS title,
                s.persona_id AS persona_id,
                s.created_at AS created_at,
                s.updated_at AS updated_at,
                COUNT(m.id) AS message_count
            FROM sessions AS s
            LEFT JOIN messages AS m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC, s.created_at DESC;
            """
        ).fetchall()
        items = [
            {
                "session_id": row["session_id"],
                "title": row["title"],
                "persona_id": row["persona_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message_count": int(row["message_count"]),
                "current": row["session_id"] == runtime.session_id,
            }
            for row in rows
        ]
        return _json_response(jsonify, {"items": items, "page": 1, "page_size": len(items), "total": len(items)})

    @app.get("/api/sessions/<session_id>/messages")
    def session_messages(session_id: str):
        rows = runtime.orchestrator.conn.execute(
            """
            SELECT id, role, content, emotion, created_at, meta_json
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC;
            """,
            (session_id,),
        ).fetchall()
        items = [
            {
                "id": int(row["id"]),
                "msg_idx": msg_idx,
                "session_id": session_id,
                "role": row["role"],
                "content": row["content"],
                "emotion": row["emotion"],
                "created_at": row["created_at"],
                "meta": _loads_json(row["meta_json"]),
            }
            for msg_idx, row in enumerate(rows)
        ]
        return _json_response(jsonify, {"session_id": session_id, "items": items, "total": len(items)})

    @app.post("/api/plan/decompose")
    def decompose_plan():
        data = request.get_json(silent=True) or {}
        goal = str(data.get("goal") or data.get("message") or "").strip()
        if not goal:
            return _json_response(jsonify, {"error": "missing goal"}, status=400)
        plan = _create_http_plan(goal)
        plan = save_plan(runtime.orchestrator.conn, plan)
        return _json_response(jsonify, {"ok": True, "plan": plan}, status=201)

    @app.post("/api/plan/<plan_id>/execute")
    def execute_plan_step(plan_id: str):
        data = request.get_json(silent=True) or {}
        timeout_seconds = _coerce_timeout(data.get("timeout"), default=20.0)
        step_id = data.get("step_id")
        plan = get_plan(runtime.orchestrator.conn, plan_id)
        if plan is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        step = _next_executable_step(plan) if step_id is None else _find_plan_step(plan, int(step_id))
        if step is None:
            plan["status"] = "done" if all(s["status"] == "done" for s in plan["steps"]) else plan["status"]
            plan = update_plan(runtime.orchestrator.conn, plan)
            return _json_response(jsonify, {"ok": True, "status": plan["status"], "plan": plan})
        consent_request_id = str(data.get("consent_request_id") or "").strip()
        if consent_request_id:
            if not _is_plan_consent_allowed(runtime, consent_request_id):
                return _json_response(jsonify, {"error": "consent_not_allowed", "status": "consent_not_allowed"}, status=403)
        elif step.get("requires_auth") and not bool(data.get("consent_granted", False)):
            step["status"] = "consent"
            plan["status"] = "paused"
            step["consent_request_id"] = _submit_plan_consent(runtime, plan, step)
            plan = update_plan(runtime.orchestrator.conn, plan)
            step = _find_plan_step(plan, int(step["id"])) or step
            return _json_response(
                jsonify,
                {
                    "ok": False,
                    "error": "requires_consent",
                    "status": "requires_consent",
                    "consent_request_id": step["consent_request_id"],
                    "consent_payload": _plan_consent_payload(runtime, step["consent_request_id"]),
                    "plan": plan,
                    "step": step,
                },
                status=409,
            )
        if timeout_seconds <= 0:
            step["status"] = "failed"
            step["error"] = "步骤超时，可重试或跳过。"
            plan["status"] = "paused"
            plan = update_plan(runtime.orchestrator.conn, plan)
            step = _find_plan_step(plan, int(step["id"])) or step
            return _json_response(
                jsonify,
                {"ok": False, "error": "timeout", "status": "timeout", "plan": plan, "step": step},
                status=408,
            )
        step["status"] = "done"
        step["result"] = _plan_step_result(step["title"])
        step["error"] = None
        plan["updated_at"] = time.time()
        plan["status"] = "done" if all(s["status"] == "done" for s in plan["steps"]) else "running"
        plan = update_plan(runtime.orchestrator.conn, plan)
        step = _find_plan_step(plan, int(step["id"])) or step
        return _json_response(jsonify, {"ok": True, "status": step["status"], "plan": plan, "step": step})

    @app.post("/api/plan/<plan_id>/pause")
    def pause_plan(plan_id: str):
        plan = get_plan(runtime.orchestrator.conn, plan_id)
        if plan is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        plan["status"] = "paused"
        plan["updated_at"] = time.time()
        plan = update_plan(runtime.orchestrator.conn, plan)
        return _json_response(jsonify, {"ok": True, "plan": plan})

    @app.post("/api/plan/<plan_id>/resume")
    def resume_plan(plan_id: str):
        plan = get_plan(runtime.orchestrator.conn, plan_id)
        if plan is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        plan["status"] = "running"
        plan["updated_at"] = time.time()
        plan = update_plan(runtime.orchestrator.conn, plan)
        return _json_response(jsonify, {"ok": True, "plan": plan})

    @app.post("/api/plan/<plan_id>/cancel")
    def cancel_plan(plan_id: str):
        plan = get_plan(runtime.orchestrator.conn, plan_id)
        if plan is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        plan["status"] = "cancelled"
        plan["updated_at"] = time.time()
        delete_plan(runtime.orchestrator.conn, plan_id)
        return _json_response(jsonify, {"ok": True, "plan": plan})

    @app.post("/api/chat")
    def chat():
        data = request.get_json(silent=True) or {}
        if not model_lock.acquire(blocking=False):
            return _json_response(jsonify, {"error": "model_loading", "reply": "", "blocked": False}, status=503)
        if bool(data.get("stream", False)):
            message = str(data.get("message", ""))

            def generate():
                try:
                    for event in process_chat_message_stream(runtime, message):
                        yield _sse_event(event)
                except Exception as exc:
                    yield _sse_event(
                        {
                            "done": True,
                            "error": str(exc),
                            "reply": "",
                            "blocked": False,
                            "memory_saved": [],
                            "memory_recall_count": 0,
                        }
                    )
                finally:
                    model_lock.release()

            return _sse_response(Response, generate())
        try:
            payload = process_chat_message(runtime, str(data.get("message", "")))
            return _json_response(jsonify, payload)
        except Exception as exc:
            return (
                _json_response(
                    jsonify,
                    {
                        "reply": "",
                        "blocked": False,
                        "memory_saved": [],
                        "memory_recall_count": 0,
                        "error": str(exc),
                    }
                ),
                500,
            )
        finally:
            model_lock.release()

    @app.get("/api/consent")
    def consent_status():
        gateway = getattr(runtime.orchestrator, "consent_gateway", None)
        if gateway is None:
            return _json_response(
                jsonify,
                {
                    "title": "出站同意",
                    "body": "当前没有待处理的同意请求。",
                    "purpose_type": "skill_cloud_inference",
                },
            )
        return _json_response(jsonify, gateway.to_modal_payload())

    @app.post("/api/consent")
    def consent_decision():
        data = request.get_json(silent=True) or {}
        request_id = str(data.get("request_id", "")).strip()
        allowed = bool(data.get("allowed", False))
        if not request_id:
            return _json_response(jsonify, {"error": "missing request_id"}, status=400)
        try:
            result = runtime.orchestrator.resume_pending_turn(request_id, allowed=allowed)
            return _json_response(jsonify, turn_result_to_payload(result))
        except KeyError as exc:
            gateway = getattr(runtime.orchestrator, "consent_gateway", None)
            pending = gateway.get_pending(request_id) if gateway is not None else None
            if pending is None:
                return _json_response(jsonify, {"error": str(exc)}, status=404)
            artifact = gateway.decide(request_id, allowed)
            return _json_response(jsonify, {"ok": True, "artifact": artifact, "consent": gateway.to_modal_payload(request_id)})

    @app.post("/api/clear")
    def clear_chat():
        deleted = clear_session_messages(runtime.orchestrator.conn, runtime.session_id)
        return _json_response(jsonify, {"ok": True, "deleted": deleted})

    @app.get("/api/consent-placeholder")
    def consent_placeholder():
        gateway = getattr(runtime.orchestrator, "consent_gateway", None)
        if gateway is None:
            return _json_response(
                jsonify,
                {
                    "title": "出站同意",
                    "body": "当前没有待处理的同意请求。",
                    "purpose_type": "skill_cloud_inference",
                },
            )
        return _json_response(jsonify, gateway.to_modal_payload())

    return app


def _json_safe(payload: Any) -> Any:
    """摘要：递归转换为 Flask 可 JSON 序列化的结构。"""
    if payload is None or isinstance(payload, (str, int, float, bool)):
        return payload
    if isinstance(payload, datetime):
        return payload.isoformat()
    if isinstance(payload, dict):
        return {str(key): _json_safe(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_json_safe(item) for item in payload]
    return str(payload)


def _json_response(jsonify, payload: Any, *, status: int = 200):
    """摘要：统一返回递归清理后的 JSON 响应。"""
    response = jsonify(_json_safe(payload))
    response.content_type = "application/json; charset=utf-8"
    return response if status == 200 else (response, status)


def _sse_event(payload: Any) -> str:
    """摘要：把 JSON payload 包装为一条 SSE data 事件。"""
    return f"data: {json.dumps(_json_safe(payload), ensure_ascii=False)}\n\n"


def _sse_response(response_factory: Any, generator: Any) -> Any:
    """摘要：构造禁用缓冲的 SSE 响应，确保 token 尽快 flush 到前端。"""
    response = response_factory(generator, mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response



def _loads_json(raw: str | None) -> dict[str, Any]:
    """摘要：安全解析数据库 JSON 字段。"""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _memory_row(conn, memory_id: int) -> dict[str, Any] | None:
    """摘要：读取单条记忆并保持与列表接口字段一致。"""
    row = conn.execute(
        "SELECT id, session_id, content, body, memory_type, status, source, created_at, modified_at, metadata, meta_json "
        "FROM memory_chunks WHERE id = ?;",
        (memory_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "session_id": row["session_id"],
        "content": row["content"],
        "body": row["body"],
        "memory_type": row["memory_type"],
        "status": row["status"],
        "source": row["source"],
        "created_at": row["created_at"],
        "modified_at": row["modified_at"],
        "metadata": _loads_json(row["metadata"]),
        "meta": _loads_json(row["meta_json"]),
    }


def _create_http_plan(goal: str) -> dict[str, Any]:
    """摘要：为桌面原型生成最小任务计划结构。"""
    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    now = time.time()
    steps = _decompose_goal_steps(goal)
    return {
        "id": plan_id,
        "goal": goal,
        "status": "pending",
        "progress": 0,
        "created_at": now,
        "updated_at": now,
        "steps": [
            {
                "id": idx,
                "title": step["title"],
                "deps": step["deps"],
                "risk": step["risk"],
                "requires_auth": step["risk"] == "high",
                "status": "pending",
                "result": None,
                "error": None,
            }
            for idx, step in enumerate(steps)
        ],
    }


def _decompose_goal_steps(goal: str) -> list[dict[str, Any]]:
    """摘要：用轻量规则拆解用户目标，后续可替换为真正 PlanOrchestrator。"""
    if any(keyword in goal for keyword in ("写", "制作", "实现", "开发", "代码")):
        return [
            {"title": "理解需求：解析目标功能与约束", "deps": [], "risk": "low"},
            {"title": "设计方案：确定模块边界与数据流", "deps": [0], "risk": "low"},
            {"title": "实现核心逻辑：完成主要代码改动", "deps": [1], "risk": "medium"},
            {"title": "运行验证：执行相关测试与检查", "deps": [2], "risk": "low"},
            {"title": "整理交付：总结变更与后续风险", "deps": [3], "risk": "low"},
        ]
    if any(keyword in goal for keyword in ("部署", "安装", "下载", "网络", "权限")):
        return [
            {"title": "检查环境：确认运行时、路径与权限", "deps": [], "risk": "low"},
            {"title": "准备依赖：下载或定位所需组件", "deps": [0], "risk": "medium"},
            {"title": "执行变更：修改系统或服务配置", "deps": [1], "risk": "high"},
            {"title": "验证结果：检查服务状态与日志", "deps": [2], "risk": "low"},
        ]
    if any(keyword in goal for keyword in ("分析", "研究", "评估", "梳理")):
        return [
            {"title": "收集上下文：整理相关代码与数据", "deps": [], "risk": "low"},
            {"title": "结构化分析：提取关键事实与差异", "deps": [0], "risk": "low"},
            {"title": "输出结论：给出判断和建议路径", "deps": [1], "risk": "low"},
        ]
    return [
        {"title": "理解目标：确认任务边界", "deps": [], "risk": "low"},
        {"title": "制定方案：拆分可执行步骤", "deps": [0], "risk": "low"},
        {"title": "执行核心步骤", "deps": [1], "risk": "medium"},
        {"title": "验证与收尾", "deps": [2], "risk": "low"},
    ]


def _find_plan_step(plan: dict[str, Any], step_id: int) -> dict[str, Any] | None:
    """摘要：按前端步骤 ID 查找计划步骤。"""
    for step in plan.get("steps", []):
        if int(step.get("id", -1)) == step_id:
            return step
    return None


def _next_executable_step(plan: dict[str, Any]) -> dict[str, Any] | None:
    """摘要：选择依赖已完成的下一个 pending 步骤。"""
    steps = plan.get("steps", [])
    for step in steps:
        if step.get("status") != "pending":
            continue
        deps = step.get("deps") or []
        if all(0 <= int(dep) < len(steps) and steps[int(dep)].get("status") == "done" for dep in deps):
            return step
    return None


def _coerce_timeout(value: Any, *, default: float) -> float:
    """摘要：解析前端传入的步骤执行超时时间。"""
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _plan_step_result(title: str) -> str:
    """摘要：生成非 streaming 模式下的步骤执行结果摘要。"""
    return f"步骤已完成：{title}"


def _submit_plan_consent(runtime: DesktopRuntime, plan: dict[str, Any], step: dict[str, Any]) -> str:
    """摘要：为计划高危步骤创建真实 A3 pending consent。"""
    gateway = getattr(runtime.orchestrator, "consent_gateway", None)
    if gateway is None:
        return uuid.uuid4().hex
    request = ConsentRequest(
        plan_id=str(plan["id"]),
        step_id=str(step["id"]),
        skill_id="desktop_plan_step",
        operation="execute_step",
        risk_level=str(step.get("risk") or "high"),
        impact_scope="plan_step",
        source="desktop_http_plan",
        metadata={
            "purpose_type": "plugin_high_risk_skill",
            "goal": str(plan.get("goal") or ""),
            "step_title": str(step.get("title") or ""),
            "permission": "execute_high_risk_plan_step",
        },
    )
    gateway.submit(request)
    artifact = gateway.last_artifact or {}
    return str(artifact.get("request_id") or uuid.uuid4().hex)


def _plan_consent_payload(runtime: DesktopRuntime, request_id: str) -> dict[str, Any]:
    """摘要：返回前端展示计划 consent 所需的结构化信息。"""
    gateway = getattr(runtime.orchestrator, "consent_gateway", None)
    if gateway is None:
        return {
            "request_id": request_id,
            "permission": "execute_high_risk_plan_step",
            "risk_desc": "该步骤被标记为高风险，需要用户确认。",
        }
    payload = gateway.to_modal_payload(request_id)
    payload["permission"] = "execute_high_risk_plan_step"
    payload["risk_desc"] = "该步骤可能影响本地文件、依赖、网络或系统配置，执行前需要确认。"
    return payload


def _is_plan_consent_allowed(runtime: DesktopRuntime, request_id: str) -> bool:
    """摘要：验证计划步骤 consent 已存在且用户已允许。"""
    gateway = getattr(runtime.orchestrator, "consent_gateway", None)
    if gateway is None:
        return False
    pending = gateway.get_pending(request_id)
    return bool(pending is not None and pending.decided and pending.allowed)


def _parse_privacy_mode(raw: Any) -> PrivacyMode | None:
    """摘要：解析前端隐私模式枚举，兼容原型大写值。"""
    text = str(raw or "").strip()
    aliases = {
        "LOCAL_ONLY": PrivacyMode.LOCAL_ONLY,
        "local_only": PrivacyMode.LOCAL_ONLY,
        "LAN": PrivacyMode.ASK_BEFORE_CLOUD,
        "ask_before_cloud": PrivacyMode.ASK_BEFORE_CLOUD,
        "ALWAYS_ASK": PrivacyMode.ALWAYS_ASK,
        "always_ask": PrivacyMode.ALWAYS_ASK,
        "CLOUD": PrivacyMode.AUTO_ROUTE_CLOUD,
        "AUTO_ROUTE_CLOUD": PrivacyMode.AUTO_ROUTE_CLOUD,
        "auto_route_cloud": PrivacyMode.AUTO_ROUTE_CLOUD,
    }
    return aliases.get(text)


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    """摘要：追加写入本地 JSONL 审计/反馈记录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_safe(item), ensure_ascii=False) + "\n")


def _ensure_auth_file(root: Path) -> dict[str, Any]:
    """摘要：确保本地登录 token 文件存在，并返回认证配置。"""
    path = root / "auth.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict) and str(data.get("token") or ""):
            data.setdefault("account_name", "local-user")
            return data
    data = {
        "token": secrets.token_hex(16),
        "created_at": time.time(),
        "account_name": "local-user",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _auth_status_payload(runtime: DesktopRuntime, auth: dict[str, Any]) -> dict[str, Any]:
    """摘要：返回登录面板需要的本地认证状态，不泄露完整 token。"""
    token = str(auth.get("token") or "")
    return {
        "logged_in": bool(getattr(runtime, "logged_in", False)),
        "account_name": str(getattr(runtime, "account_name", auth.get("account_name") or "local-user")),
        "token_preview": f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "",
        "created_at": auth.get("created_at"),
    }


def _read_improve_plan_state(root: Path) -> dict[str, Any]:
    """摘要：读取本地改进计划开关状态。"""
    path = root / "improve_plan.json"
    if not path.is_file():
        return {"enabled": False, "last_upload_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"enabled": False, "last_upload_at": None}
    return data if isinstance(data, dict) else {"enabled": False, "last_upload_at": None}


def _write_improve_plan_state(root: Path, state: dict[str, Any]) -> None:
    """摘要：持久化本地改进计划开关状态。"""
    path = root / "improve_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(state), ensure_ascii=False, indent=2), encoding="utf-8")


def _improve_plan_payload(runtime: DesktopRuntime) -> dict[str, Any]:
    """摘要：构造改进计划状态响应；当前版本只做本地队列标记，不上传。"""
    state = _read_improve_plan_state(runtime.paths.root)
    runtime.improve_plan_enabled = bool(state.get("enabled", False)) and bool(getattr(runtime, "logged_in", False))
    return {
        "enabled": bool(getattr(runtime, "improve_plan_enabled", False)),
        "queued_count": _count_queueable_feedback(runtime.paths.root / "feedback.jsonl"),
        "last_upload_at": state.get("last_upload_at"),
    }


def _count_queueable_feedback(path: Path) -> int:
    """摘要：统计本地反馈队列中可上传条目数量。"""
    if not path.is_file():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and bool(item.get("queueable", False)):
            count += 1
    return count


def _resolve_message_id(conn, session_id: str, raw_msg_id: Any) -> int | None:
    """摘要：解析前端传入的消息 ID；兼容 msg_idx。"""
    if raw_msg_id is None or raw_msg_id == "":
        return None
    try:
        numeric = int(raw_msg_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        "SELECT id FROM messages WHERE id = ? AND session_id = ?;",
        (numeric, session_id),
    ).fetchone()
    if row is not None:
        return int(row["id"])
    rows = conn.execute(
        "SELECT id FROM messages WHERE session_id = ? ORDER BY id ASC;",
        (session_id,),
    ).fetchall()
    if 0 <= numeric < len(rows):
        return int(rows[numeric]["id"])
    return None


def _message_meta(conn, message_id: int) -> dict[str, Any]:
    """摘要：读取消息 meta_json 并安全解析。"""
    row = conn.execute("SELECT meta_json FROM messages WHERE id = ?;", (message_id,)).fetchone()
    if row is None:
        return {}
    return _loads_json(row["meta_json"])


def _persona_files(runtime: DesktopRuntime) -> list[Path]:
    """摘要：查找桌面端可用 persona YAML 文件。"""
    roots = [
        runtime.paths.personas_dir,
        Path("configs") / "personas",
        Path(__file__).resolve().parents[5] / "configs" / "personas",
    ]
    files: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
            files.setdefault(path.stem, path)
    return list(files.values())


def _persona_payload(path: Path, runtime: DesktopRuntime) -> dict[str, Any]:
    """摘要：将 persona YAML 转换为前端只读列表结构。"""
    persona = load_persona_file(path)
    raw = persona.raw
    ocean = persona.ocean
    ocean_values = (
        [
            round(float(ocean.openness) * 100),
            round(float(ocean.conscientiousness) * 100),
            round(float(ocean.extraversion) * 100),
            round(float(ocean.agreeableness) * 100),
            round(float(ocean.neuroticism) * 100),
        ]
        if ocean is not None
        else []
    )
    traits = raw.get("traits") or raw.get("tone_keywords") or []
    if not isinstance(traits, list):
        traits = []
    return {
        "id": persona.persona_id,
        "name": persona.name,
        "avatar": str(raw.get("avatar") or persona.name[:1] or "伴"),
        "desc": str(raw.get("description") or raw.get("desc") or persona.system_prompt[:160]),
        "ocean": ocean_values,
        "traits": [str(item) for item in traits],
        "anchor": persona.system_prompt,
        "active": persona.persona_id == runtime.orchestrator.session_core.persona.persona_id,
    }


def _model_payload(model: Any, runtime: DesktopRuntime, model_state: dict[str, Any]) -> dict[str, Any]:
    """摘要：将模型描述转换为前端模型卡片结构。"""
    model_id = str(getattr(model, "model_id", "") or getattr(model, "display_name", ""))
    gguf_path = getattr(model, "gguf_path", None)
    size = None
    if gguf_path:
        path = Path(str(gguf_path))
        if path.is_file():
            size = path.stat().st_size
    active_id = str(model_state.get("active") or runtime.model_label)
    enabled_key = f"enabled:{model_id}"
    model_type = "cloud" if str(getattr(model, "backend", "")).lower() == "cloud" else "local"
    return {
        "id": model_id,
        "name": str(getattr(model, "display_name", None) or model_id),
        "type": model_type,
        "locked": model_type == "cloud" and not bool(getattr(runtime, "logged_in", False)),
        "enabled": bool(model_state.get(enabled_key, getattr(model, "status", "") == "ready")),
        "active": model_id == active_id or str(getattr(model, "display_name", "")) == runtime.model_label,
        "status": str(getattr(model, "status", "unknown")),
        "meta": {
            "source": str(getattr(model, "source", "")),
            "backend": str(getattr(model, "backend", "")),
            "architecture": getattr(model, "architecture", None),
            "n_ctx": getattr(model, "n_ctx", None),
            "size": size,
            "ram": None,
        },
    }


def _find_model_descriptor(model_id: str, runtime: DesktopRuntime) -> Any | None:
    """摘要：按模型 ID 或显示名查找当前可见模型描述。"""
    for model in discover_models(data_root_override=runtime.paths.root):
        current_id = str(getattr(model, "model_id", "") or getattr(model, "display_name", ""))
        display_name = str(getattr(model, "display_name", "") or "")
        if model_id in {current_id, display_name}:
            return model
    return None


def _load_local_model_backend(runtime: DesktopRuntime, model: Any) -> object:
    """摘要：为本地 GGUF 描述创建新的推理后端实例。"""
    old_backend = runtime.orchestrator.backend
    n_ctx = int(getattr(old_backend, "n_ctx", None) or getattr(model, "n_ctx", None) or 2048)
    n_gpu_layers = int(getattr(old_backend, "n_gpu_layers", 0) or 0)
    model_config = runtime_config_from_descriptor(model)
    return create_llama_backend(
        str(model.gguf_path),
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        run_health_check=True,
        model_config=model_config,
    )


def _extension_payloads(
    plugin_gateway: PluginSecurityGateway,
    runtime: DesktopRuntime,
    extension_state: dict[str, bool],
) -> list[dict[str, Any]]:
    """摘要：聚合 mock plugins 与已安装 skills，形成扩展只读列表。"""
    items: list[dict[str, Any]] = []
    for plugin in plugin_gateway.list_plugins():
        extension_id = str(plugin["plugin_id"])
        enabled = bool(extension_state.get(extension_id, True))
        items.append(
            {
                "id": extension_id,
                "name": extension_id,
                "type": "plugin",
                "source": "local",
                "status": "enabled" if enabled else "disabled",
                "enabled": enabled,
                "version": plugin.get("version"),
                "description": plugin.get("description"),
                "permissions": plugin.get("permissions", []),
                "capabilities": plugin.get("capabilities", []),
            }
        )
    for manifest in load_installed_manifests(runtime.paths.root):
        extension_id = manifest.name
        enabled = bool(extension_state.get(extension_id, True))
        items.append(
            {
                "id": extension_id,
                "name": manifest.name,
                "type": "skill",
                "source": "local",
                "status": "enabled" if enabled else "disabled",
                "enabled": enabled,
                "version": manifest.version_raw,
                "description": manifest.description,
                "permissions": list(manifest.permissions),
                "capabilities": [],
            }
        )
    return items


def start_desktop_http(runtime: DesktopRuntime) -> DesktopHttpServer:
    """摘要：在后台线程启动 127.0.0.1 HTTP 服务。"""
    port = _pick_port()
    app = create_desktop_app(runtime)
    try:
        from waitress import serve
    except ImportError as exc:
        raise ImportError("桌面 HTTP 需要 waitress，请安装 `pip install -e \".[desktop]\"`") from exc

    def _serve() -> None:
        serve(app, host=_ALLOWED_HOST, port=port, threads=4)

    thread = threading.Thread(
        target=_serve,
        daemon=True,
        name="desktop-http",
    )
    thread.start()
    return DesktopHttpServer(port=port, thread=thread)
