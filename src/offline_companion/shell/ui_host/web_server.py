"""web_server：127.0.0.1 Flask WebUI 壳（Sprint 6.2；A1 宿主）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.turn_payload import process_chat_message

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_ALLOWED_HOST = "127.0.0.1"


@dataclass
class WebRuntime:
    """摘要：WebUI 会话运行时（编排器 + 可变记忆开关）。"""

    orchestrator: ConversationOrchestrator
    memory_on: bool
    session_id: str


def create_app(runtime: WebRuntime):
    """摘要：创建 Flask 应用并注册路由。

    参数：
        runtime: Web 会话运行时。

    返回值：
        配置完成的 ``Flask`` 实例。

    Raises:
        ImportError: 未安装 ``flask``（``pip install -e '.[webui]'``）。
    """
    try:
        from flask import Flask, jsonify, render_template, request
    except ImportError as e:
        raise ImportError("WebUI 需要 Flask：pip install -e '.[webui]'") from e

    app = Flask(__name__, template_folder=str(_TEMPLATE_DIR))

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        return jsonify(
            {
                "memory_on": runtime.memory_on,
                "session_id": runtime.session_id,
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
        return jsonify(payload)

    return app


def run_web(
    runtime: WebRuntime,
    *,
    host: str = _ALLOWED_HOST,
    port: int = 8765,
) -> None:
    """摘要：启动本地 WebUI（仅允许 127.0.0.1）。

    参数：
        runtime: Web 会话运行时。
        host: 监听地址；非 ``127.0.0.1`` 时强制回落。
        port: 端口。

    Raises:
        ImportError: 未安装 ``flask``。
    """
    if host != _ALLOWED_HOST:
        host = _ALLOWED_HOST
    app = create_app(runtime)
    # threaded=True：浏览器连续 fetch 时不阻塞单线程开发服务器
    app.run(host=host, port=port, debug=False, threaded=True)
