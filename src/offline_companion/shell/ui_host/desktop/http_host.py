"""http_host：桌面壳内嵌 127.0.0.1 HTTP（避免 file:// + pywebview.api 序列化问题）。"""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import offline_companion.shell.ui_host.desktop as _desktop_pkg
from offline_companion.runtime.storage_index.engine import clear_session_messages
from offline_companion.shell.ui_host.turn_payload import process_chat_message
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime

_ALLOWED_HOST = "127.0.0.1"


def _static_dir() -> Path:
    return Path(_desktop_pkg.__file__).resolve().parent / "static"


def _pick_port() -> int:
    """摘要：选取本机空闲端口。"""
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
    """摘要：创建桌面壳 Flask 应用（静态页 + JSON API）。"""
    try:
        from flask import Flask, jsonify, request, send_from_directory
    except ImportError as e:
        raise ImportError("桌面壳 HTTP 需要 Flask：pip install -e '.[webui,desktop]'") from e

    static = _static_dir()
    app = Flask(__name__, static_folder=str(static), static_url_path="")

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
        runtime.memory_on = bool(data.get("enabled", False))
        return jsonify({"memory_on": runtime.memory_on})

    @app.post("/api/chat")
    def chat():
        data = request.get_json(silent=True) or {}
        payload = process_chat_message(runtime, str(data.get("message", "")))
        return jsonify(_json_safe(payload))

    @app.post("/api/clear")
    def clear_chat():
        """摘要：清空当前会话消息（保留会话行与人设绑定）。"""
        deleted = clear_session_messages(
            runtime.orchestrator.conn,
            runtime.session_id,
        )
        return jsonify({"ok": True, "deleted": deleted})

    @app.get("/api/consent-placeholder")
    def consent_placeholder():
        return jsonify(
            {
                "title": "出站同意（占位）",
                "body": "Sprint 7.2 将在此展示 Consent Artifact 详情并收集用户决定。",
                "purpose_type": "skill_cloud_call",
            }
        )

    return app


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    """摘要：确保 JSON 可序列化（pywebview / Flask 通用）。"""
    out: dict[str, Any] = {}
    for key, val in payload.items():
        if val is None or isinstance(val, (str, int, float, bool)):
            out[key] = val
        elif isinstance(val, list):
            out[key] = [str(x) for x in val]
        else:
            out[key] = str(val)
    return out


def start_desktop_http(runtime: DesktopRuntime) -> DesktopHttpServer:
    """摘要：在后台线程启动 127.0.0.1 HTTP 服务。

    参数：
        runtime: 须含 ``orchestrator``、``memory_on``、``session_id``；
            可选 ``privacy_mode``、``model_label``（桌面展示字段）。

    返回值：
        含端口与线程的句柄。
    """
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
