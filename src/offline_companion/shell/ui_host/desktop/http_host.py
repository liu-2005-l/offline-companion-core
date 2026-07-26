"""摘要：桌面壳内嵌 127.0.0.1 HTTP 宿主。"""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import offline_companion.shell.ui_host.desktop as _desktop_pkg
from offline_companion.core.memory_lifecycle.fts_ops import (
    count_memory_rows,
    invalidate_memory_chunk,
    restore_memory_chunk,
)
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.runtime.storage_index.engine import clear_session_messages
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shell.ui_host.plugin_loader import (
    PluginSecurityGateway,
    build_mock_plugin_registry,
)
from offline_companion.shell.ui_host.turn_payload import (
    process_chat_message,
    turn_result_to_payload,
)

_ALLOWED_HOST = "127.0.0.1"


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
        from flask import Flask, jsonify, request, send_from_directory
    except ImportError as exc:
        raise ImportError("桌面壳 HTTP 需要 Flask，请安装 `pip install -e \".[webui,desktop]\"`") from exc

    static = _static_dir()
    app = Flask(__name__, static_folder=str(static), static_url_path="")
    plugin_gateway = PluginSecurityGateway(runtime, build_mock_plugin_registry())

    @app.get("/")
    def index():
        return send_from_directory(static, "index.html")

    @app.get("/api/status")
    def status():
        return jsonify(
            {
                "memory_on": runtime.memory_on,
                "session_id": runtime.session_id,
                "persona_name": runtime.persona_name,
                "privacy_mode": runtime.privacy_mode.value,
                "model_label": runtime.model_label,
            }
        )

    @app.post("/api/memory")
    def set_memory():
        data = request.get_json(silent=True) or {}
        runtime.memory_on = bool(data.get("enabled", True))
        return jsonify({"memory_on": runtime.memory_on, "locked": False})

    @app.get("/api/plugins")
    def plugins():
        return jsonify({"items": plugin_gateway.list_plugins()})

    @app.post("/api/plugins/session")
    def create_plugin_session():
        data = request.get_json(silent=True) or {}
        try:
            payload = plugin_gateway.create_session(str(data.get("plugin_id", "")))
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/plugins/session/<session_id>/destroy")
    def destroy_plugin_session(session_id: str):
        plugin_gateway.destroy_session(session_id)
        return jsonify({"ok": True})

    @app.get("/api/plugins/frame/<plugin_id>")
    def plugin_frame(plugin_id: str):
        try:
            html = plugin_gateway.frame_html(plugin_id)
            return html, 200, {"Content-Type": "text/html; charset=utf-8"}
        except Exception as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/plugins/message")
    def plugin_message():
        data = request.get_json(silent=True) or {}
        try:
            payload = plugin_gateway.handle_bridge_message(data)
            return jsonify(payload)
        except Exception as exc:
            return (
                jsonify(
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
        return jsonify(
            {
                "items": rows,
                "grouped": grouped,
                "page": page,
                "page_size": page_size,
                "total": int(total),
            }
        )

    @app.post("/api/memories/<int:memory_id>/invalidate")
    def invalidate_memory(memory_id: int):
        ok = invalidate_memory_chunk(runtime.orchestrator.conn, memory_id)
        return jsonify({"ok": ok})

    @app.post("/api/memories/<int:memory_id>/restore")
    def restore_memory(memory_id: int):
        ok = restore_memory_chunk(runtime.orchestrator.conn, memory_id)
        return jsonify({"ok": ok})

    @app.post("/api/memories/<int:memory_id>/delete")
    def delete_memory(memory_id: int):
        ok = MemoryLifecycleManager.delete_memory_chunk(runtime.orchestrator.conn, memory_id)
        return jsonify({"ok": ok})

    @app.post("/api/chat")
    def chat():
        data = request.get_json(silent=True) or {}
        try:
            payload = process_chat_message(runtime, str(data.get("message", "")))
            return jsonify(_json_safe(payload))
        except Exception as exc:
            return (
                jsonify(
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

    @app.get("/api/consent")
    def consent_status():
        gateway = getattr(runtime.orchestrator, "consent_gateway", None)
        if gateway is None:
            return jsonify(
                {
                    "title": "出站同意",
                    "body": "当前没有待处理的同意请求。",
                    "purpose_type": "skill_cloud_inference",
                }
            )
        return jsonify(gateway.to_modal_payload())

    @app.post("/api/consent")
    def consent_decision():
        data = request.get_json(silent=True) or {}
        request_id = str(data.get("request_id", "")).strip()
        allowed = bool(data.get("allowed", False))
        if not request_id:
            return jsonify({"error": "missing request_id"}), 400
        try:
            result = runtime.orchestrator.resume_pending_turn(request_id, allowed=allowed)
            return jsonify(_json_safe(turn_result_to_payload(result)))
        except KeyError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/clear")
    def clear_chat():
        deleted = clear_session_messages(runtime.orchestrator.conn, runtime.session_id)
        return jsonify({"ok": True, "deleted": deleted})

    @app.get("/api/consent-placeholder")
    def consent_placeholder():
        gateway = getattr(runtime.orchestrator, "consent_gateway", None)
        if gateway is None:
            return jsonify(
                {
                    "title": "出站同意",
                    "body": "当前没有待处理的同意请求。",
                    "purpose_type": "skill_cloud_inference",
                }
            )
        return jsonify(gateway.to_modal_payload())

    return app


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    """摘要：确保 payload 可被 JSON 安全序列化。"""
    out: dict[str, Any] = {}
    for key, val in payload.items():
        if val is None or isinstance(val, (str, int, float, bool)):
            out[key] = val
        elif isinstance(val, list):
            out[key] = [str(item) for item in val]
        else:
            out[key] = str(val)
    return out


def start_desktop_http(runtime: DesktopRuntime) -> DesktopHttpServer:
    """摘要：在后台线程启动 127.0.0.1 HTTP 服务。"""
    port = _pick_port()
    app = create_desktop_app(runtime)
    thread = threading.Thread(
        target=lambda: app.run(
            host=_ALLOWED_HOST,
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False,
        ),
        daemon=True,
        name="desktop-http",
    )
    thread.start()
    return DesktopHttpServer(port=port, thread=thread)
