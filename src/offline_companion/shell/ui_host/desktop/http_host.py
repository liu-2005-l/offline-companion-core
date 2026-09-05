"""摘要：桌面壳内嵌 127.0.0.1 HTTP 宿主。"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import shutil
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import Any

import offline_companion.shell.ui_host.desktop as _desktop_pkg
from offline_companion import __version__
from offline_companion.core.decomposition_result import NotDecomposableResult
from offline_companion.core.decomposition_sample_library import (
    DecompositionSample,
    InvalidSampleTransitionError,
    SampleState,
)
from offline_companion.core.diagnostics import HealthChecker, HealthCheckResult, HealthStatus
from offline_companion.core.event_stream import TRAJECTORY_PROJECTION
from offline_companion.core.hard_gate import HardGate
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.event_types import SemanticEvent
from offline_companion.core.memory_lifecycle.fts_ops import (
    count_memory_rows,
    invalidate_memory_chunk,
    restore_memory_chunk,
    update_memory_chunk,
)
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.semantic_embedding_provider import (
    SemanticEmbeddingProvider,
    embedding_space_of,
)
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.plan_enums import PlanErrorCode, PlanEventName
from offline_companion.core.plan_orchestrator import (
    ConsentRequest,
    PlanOrchestrator,
    PlanStep,
    TaskContext,
)
from offline_companion.core.plan_orchestrator import PlanStatus as CorePlanStatus
from offline_companion.core.plan_orchestrator import StepStatus as CoreStepStatus
from offline_companion.core.skill_execution_tracker import SkillExecutionTracker
from offline_companion.core.state_manager import StateManager
from offline_companion.core.subagent_scheduler import SubagentScheduler
from offline_companion.core.ui_annotation import AnnotationError, AnnotationSession
from offline_companion.runtime.inference_backend import create_llama_backend
from offline_companion.runtime.storage_index.engine import (
    append_message,
    append_stream_event,
    clear_session_messages,
    latest_stream_event_seq,
    stream_events_after,
)
from offline_companion.shared.errors import (
    InferenceBackendError,
    SkillInvocationError,
    SkillManifestError,
    SkillSupplyChainError,
)
from offline_companion.shared.messages import BaseMessage
from offline_companion.shared.types import ModelDescriptor, PrivacyMode, PurposeType
from offline_companion.shell.plan_final_reply import build_final_reply
from offline_companion.shell.skill_manager.extension_manager import (
    ExtensionAlreadyInstalledError,
    ExtensionNotInstalledError,
)
from offline_companion.shell.skill_manager.extension_manager import (
    install_extension as install_local_extension,
)
from offline_companion.shell.skill_manager.extension_manager import (
    uninstall_extension as uninstall_local_extension,
)
from offline_companion.shell.skill_manager.registry import load_installed_manifests
from offline_companion.shell.skill_router import SkillDecisionEngine, load_skill_descriptions
from offline_companion.shell.ui_host.consent_feedback import (
    CONSENT_DECLINED_MESSAGE,
    consent_decision_payload,
)
from offline_companion.shell.ui_host.desktop.crash_reporting import archive_crash_report
from offline_companion.shell.ui_host.desktop.privacy_socket_guard import apply_privacy_socket_guard
from offline_companion.shell.ui_host.desktop.runtime import DesktopRuntime
from offline_companion.shell.ui_host.desktop.session_binding import (
    DesktopSessionBindingService,
    DesktopSessionContextProvider,
    SessionBindingError,
    rebind_runtime_session,
)
from offline_companion.shell.ui_host.model_downloader import (
    DownloadProgress,
    DownloadState,
    ModelDownloader,
    ThrottledProgressReporter,
)
from offline_companion.shell.ui_host.model_registry import (
    BUILTIN_MODELS,
    ModelDirectory,
    builtin_model_payload,
    describe_model,
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
from offline_companion.storage.cloud_model_repo import (
    create_cloud_model,
    delete_cloud_model,
    get_cloud_model,
    list_public_cloud_models,
    update_cloud_model,
)
from offline_companion.storage.extension_repo import init_extension_status, save_extension_status
from offline_companion.storage.json_state_store import JsonStateStore, check_state_integrity
from offline_companion.storage.persona_repo import (
    create_persona as create_persisted_persona,
)
from offline_companion.storage.persona_repo import (
    delete_persona as delete_persisted_persona,
)
from offline_companion.storage.persona_repo import (
    list_personas,
)
from offline_companion.storage.persona_repo import (
    update_persona as update_persisted_persona,
)
from offline_companion.storage.plan_repo import delete_plan, get_plan, save_plan, update_plan
from offline_companion.storage.settings_store import (
    get_all,
    get_module,
    load_settings,
    patch_module,
    update_settings,
)

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


def _health_checker_for(runtime: DesktopRuntime) -> HealthChecker:
    """摘要：构造并缓存桌面运行时的基础健康检查。"""
    checker = getattr(runtime, "_health_checker", None)
    if checker is not None:
        return checker
    checker = HealthChecker()

    def model_backend() -> HealthCheckResult:
        backend = getattr(runtime.orchestrator, "backend", None)
        report = backend.health_check() if callable(getattr(backend, "health_check", None)) else None
        if report is None:
            return HealthCheckResult("model_backend", HealthStatus.UNKNOWN, "后端未提供健康检查")
        status = HealthStatus.HEALTHY if report.ok else HealthStatus.UNHEALTHY
        return HealthCheckResult("model_backend", status, report.message, {"backend": report.backend})

    def model_file() -> HealthCheckResult:
        if runtime.local_available:
            return HealthCheckResult("model_file", HealthStatus.HEALTHY, "本地模型可用")
        return HealthCheckResult("model_file", HealthStatus.DEGRADED, runtime.local_error or "本地模型不可用")

    def event_stream() -> HealthCheckResult:
        available = getattr(runtime, "event_stream_manager", None) is not None
        return HealthCheckResult("event_stream", HealthStatus.HEALTHY if available else HealthStatus.DEGRADED, "事件流已接线" if available else "事件流未初始化")

    def memory_db() -> HealthCheckResult:
        runtime.orchestrator.conn.execute("SELECT 1").fetchone()
        return HealthCheckResult("memory_db", HealthStatus.HEALTHY, "SQLite 可读")

    def plugin_fibers() -> HealthCheckResult:
        loader = getattr(runtime, "plugin_loader", None)
        fibers = getattr(loader, "fibers", {}) if loader is not None else {}
        states = [str(getattr(fiber, "state", "")) for fiber in fibers.values()]
        if any("FAILED" in state for state in states):
            return HealthCheckResult("plugin_fibers", HealthStatus.DEGRADED, "存在失败插件", {"count": len(states)})
        return HealthCheckResult("plugin_fibers", HealthStatus.HEALTHY, "插件生命周期正常", {"count": len(states)})

    def disk_space() -> HealthCheckResult:
        free = shutil.disk_usage(runtime.paths.root).free
        status = HealthStatus.HEALTHY if free >= 1024**3 else HealthStatus.DEGRADED if free >= 500 * 1024**2 else HealthStatus.UNHEALTHY
        return HealthCheckResult("disk_space", status, f"剩余空间 {free // 1024**2} MB", {"free_bytes": free})

    def consent_store() -> HealthCheckResult:
        pending = getattr(getattr(runtime.orchestrator, "consent_gateway", None), "pending", {})
        count = len(pending)
        status = HealthStatus.DEGRADED if count > 10 else HealthStatus.HEALTHY
        return HealthCheckResult("consent_pending", status, f"待处理同意请求 {count} 个", {"count": count})

    for name, check in (("model_backend", model_backend), ("model_file", model_file), ("event_stream", event_stream), ("memory_db", memory_db), ("plugin_fibers", plugin_fibers), ("disk_space", disk_space), ("consent_pending", consent_store)):
        checker.register(name, check)
    runtime._health_checker = checker
    return checker


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
    if runtime.session_context_provider is None:
        runtime.session_context_provider = DesktopSessionContextProvider()
    if runtime.session_binding_service is None:
        runtime.session_binding_service = DesktopSessionBindingService(
            runtime.orchestrator.conn,
            context_provider=runtime.session_context_provider,
            event_stream_manager=runtime.event_stream_manager,
            semantic_embed_func=runtime.semantic_embed_func,
        )
        runtime.session_binding_service.restore_or_create(
            preferred_session_id=runtime.session_id,
            startup_persona=runtime.orchestrator.session_core.persona,
            title="UI",
        )
    runtime.session_binding_service.set_on_bind(
        lambda context: rebind_runtime_session(runtime, context)
    )
    rebind_runtime_session(runtime, runtime.session_context_provider.capture())
    plugin_gateway = PluginSecurityGateway(runtime, build_mock_plugin_registry())
    repaired_state_files = tuple(check_state_integrity(runtime.paths.root))
    runtime.repaired_state_files = tuple(
        dict.fromkeys((*runtime.repaired_state_files, *repaired_state_files))
    )
    settings_state: dict[str, Any] = load_settings(runtime.paths.root)
    persisted_privacy_mode = _parse_privacy_mode(settings_state.get("privacy_mode"))
    if persisted_privacy_mode is not None:
        runtime.privacy_mode = persisted_privacy_mode
        runtime.orchestrator.privacy_mode = persisted_privacy_mode
    runtime.memory_on = bool(settings_state.get("memory_enabled", runtime.memory_on))
    runtime.improve_plan_enabled = bool(settings_state.get("improve_plan_enabled", False))
    if runtime.state_manager is None:
        runtime.state_manager = StateManager(runtime.paths.db_path)
    if runtime.idle_detector is not None:
        runtime.idle_detector.set_threshold(float(settings_state.get("idle_threshold_seconds", 300)))
        if bool(settings_state.get("idle_think_enabled", True)):
            runtime.idle_detector.start()
        else:
            runtime.idle_detector.stop()
    active_model_id = str(
        settings_state.get("active_model_id") or runtime.active_cloud_model_id or ""
    ).strip()
    model_state: dict[str, Any] = {
        "auto": bool(settings_state.get("auto_router_enabled", False)),
        "active": active_model_id or None,
    }
    runtime.orchestrator.auto_mode_enabled = bool(model_state["auto"])
    bootstrap_cloud_model_provider = runtime.orchestrator.cloud_model_provider

    def current_cloud_model() -> dict[str, Any] | None:
        """摘要：返回当前激活云模型，缺失时保留启动期云配置。"""
        active = get_cloud_model(runtime.paths.root, str(model_state.get("active") or ""))
        if active is not None:
            return active
        return bootstrap_cloud_model_provider() if bootstrap_cloud_model_provider is not None else None

    def sync_backend_mode() -> None:
        """摘要：按隐私模式同步本地加载失败后的运行模式。"""
        if runtime.local_available:
            mode = "local"
        elif runtime.cloud_available and runtime.privacy_mode is not PrivacyMode.LOCAL_ONLY:
            mode = "cloud_fallback"
        else:
            mode = "no_backend"
        runtime.backend_mode = mode
        runtime.orchestrator.backend_mode = mode
        runtime.orchestrator.local_available = runtime.local_available
        runtime.orchestrator.cloud_available = runtime.cloud_available

    def set_active_model(model_id: str | None) -> None:
        """摘要：更新并持久化当前激活模型 ID。"""
        model_state["active"] = model_id
        update_settings(runtime.paths.root, {"active_model_id": model_id})

    def append_model_event(event_type: str, payload: dict[str, Any]) -> None:
        """摘要：记录模型生命周期事件，审计失败不影响模型切换。"""
        manager = getattr(runtime, "event_stream_manager", None)
        stream = manager.get(runtime.session_id) if manager is not None else None
        if stream is None:
            return
        try:
            stream.append(event_type, payload)
        except Exception:
            logger.warning("模型生命周期事件记录失败: %s", event_type, exc_info=True)

    def activate_downloaded_model(model_id: str, path: Path) -> None:
        """摘要：下载校验成功后替换本地推理后端并同步自动路由。"""
        model = describe_model(model_id, data_root_override=runtime.paths.root)
        model = replace(model, gguf_path=str(path), status="ready")
        old_backend = runtime.orchestrator.backend
        new_backend = _load_local_model_backend(runtime, model)
        runtime.orchestrator.backend = new_backend
        runtime.local_available = True
        runtime.local_error = None
        runtime.active_cloud_model_id = None
        runtime.model_label = model.display_name or path.name
        set_active_model(model_id)
        sync_backend_mode()

        auto_turn = runtime.auto_turn_orchestrator
        auto_router = getattr(getattr(auto_turn, "auto_bridge", None), "auto_router", None)
        if auto_router is not None:
            auto_router.reload_model(model_id, path)
        append_model_event("model/activated", {"model_id": model_id, "path": str(path)})
        append_model_event(
            "model/switched",
            {"mode": "local", "model": model_id, "reason": "download_completed"},
        )
        stop = getattr(old_backend, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                logger.warning("旧模型后端停止失败", exc_info=True)

    def run_model_download(model_id: str) -> Path:
        """摘要：执行下载并在完成后尝试自动加载模型。"""
        downloader = model_downloader()
        path = downloader.download(model_id)
        try:
            activate_downloaded_model(model_id, path)
        except Exception as exc:
            runtime.local_error = str(exc)
            runtime.local_available = False
            sync_backend_mode()
            append_model_event(
                "model/degraded",
                {"model_id": model_id, "reason": "activation_failed", "error": str(exc)},
            )
            logger.warning("下载完成但模型自动加载失败: %s", model_id, exc_info=True)
        finally:
            download_activation_pending.discard(model_id)
        return path

    runtime.orchestrator.cloud_model_provider = current_cloud_model
    configured_cloud_model = current_cloud_model()
    if configured_cloud_model is not None and all(
        str(configured_cloud_model.get(key) or "").strip()
        for key in ("endpoint", "model_name", "api_key")
    ):
        runtime.cloud_available = True
    sync_backend_mode()
    model_lock = threading.Lock()
    download_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-download")
    download_futures: dict[str, object] = {}
    download_activation_pending: set[str] = set()
    extension_state: dict[str, bool] = init_extension_status(runtime.paths.root, runtime.paths.db_path)
    runtime.logged_in = bool(getattr(runtime, "logged_in", False))
    runtime.account_name = str(getattr(runtime, "account_name", "local-user"))
    runtime.improve_plan_enabled = bool(getattr(runtime, "improve_plan_enabled", False))
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    def pending_crash_payload() -> dict[str, Any] | None:
        """摘要：读取当前运行时记录的待处理崩溃日志。"""
        raw_path = str(runtime.pending_crash_log or "").strip()
        if not raw_path:
            return None
        path = Path(raw_path)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            runtime.pending_crash_log = None
            return None
        return {"path": path, "content": content}

    def archive_pending_crash(category: str) -> Path | None:
        """摘要：归档当前待处理崩溃日志并清除运行时标记。"""
        pending = pending_crash_payload()
        if pending is None:
            return None
        archived = archive_crash_report(
            runtime.paths.root,
            pending["path"],
            category=category,
        )
        runtime.pending_crash_log = None
        return archived

    @app.get("/")
    def index():
        return send_from_directory(static, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(static, "favicon.ico")

    @app.post("/api/idle/touch")
    def idle_touch():
        """摘要：刷新 UI 空闲计时器。"""
        if runtime.idle_detector is not None:
            runtime.idle_detector.touch()
        return jsonify({"ok": True})

    @app.get("/api/idle/status")
    def idle_status():
        """摘要：返回 IdleThink 检测、提醒与后台推进快照。"""
        state_manager = runtime.state_manager
        detector = runtime.idle_detector
        return _json_response(
            jsonify,
            {
                "idle_enabled": bool(detector.running) if detector is not None else False,
                "threshold_seconds": detector.threshold_seconds if detector is not None else None,
                "current_status": (
                    state_manager.get_system_state("idle_think_status") if state_manager is not None else None
                ),
                "last_progress": (
                    state_manager.get_system_state("idle_think_progress") if state_manager is not None else None
                ),
                "last_idle_result": (
                    state_manager.get_system_state("idle_think_result") if state_manager is not None else None
                ),
            },
        )

    @app.post("/api/idle/toggle")
    def idle_toggle():
        """摘要：开启或关闭空闲检测，并可更新空闲阈值。"""
        detector = runtime.idle_detector
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("enabled", True))
        threshold_raw = data.get("threshold_seconds")
        if detector is not None and threshold_raw is not None:
            try:
                detector.set_threshold(float(threshold_raw))
            except (TypeError, ValueError):
                return _json_response(jsonify, {"error": "invalid_threshold"}, status=400)
        if detector is not None:
            if enabled:
                detector.start()
            else:
                detector.stop()
        saved = update_settings(
            runtime.paths.root,
            {
                "idle_think_enabled": enabled,
                "idle_threshold_seconds": detector.threshold_seconds if detector is not None else threshold_raw,
            },
        )
        settings_state.update(saved)
        return _json_response(
            jsonify,
            {
                "ok": True,
                "idle_enabled": bool(detector.running) if detector is not None else False,
                "threshold_seconds": detector.threshold_seconds if detector is not None else None,
                "settings": saved,
            },
        )

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
        session_context = runtime.session_context_provider.capture()
        return _json_response(
            jsonify,
            {
                "app_version": __version__,
                "memory_on": runtime.memory_on,
                "session_id": runtime.session_id,
                "session_revision": session_context.revision,
                "persona_id": runtime.orchestrator.session_core.persona.persona_id,
                "persona_name": runtime.persona_name,
                "privacy_mode": runtime.privacy_mode.value,
                "model_label": runtime.model_label,
                "backend_mode": runtime.backend_mode,
                "local_available": runtime.local_available,
                "cloud_available": runtime.cloud_available,
                "local_error": runtime.local_error,
                "repaired_state_files": list(runtime.repaired_state_files),
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

    @app.get("/api/health")
    def health():
        """摘要：返回桌面运行时的聚合健康状态。"""
        return _json_response(jsonify, _health_checker_for(runtime).run_all())

    @app.get("/api/health/<component>")
    def health_component(component: str):
        """摘要：返回指定组件的健康状态。"""
        result = _health_checker_for(runtime).component(component)
        if result is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        return _json_response(jsonify, result)

    @app.post("/api/health/run")
    def run_health():
        """摘要：强制刷新并返回全部健康检查。"""
        return _json_response(jsonify, _health_checker_for(runtime).run_all(force=True))

    @app.get("/api/diagnostics/benchmarks")
    def diagnostics_benchmarks():
        """摘要：返回最近一次性能基准报告，不在桌面请求中执行基准。"""
        path = runtime.paths.root / "benchmark_results.json"
        if not path.is_file():
            return _json_response(jsonify, {"available": False, "results": {}, "path": str(path)})
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _json_response(jsonify, {"available": False, "results": {}, "error": "invalid_report"})
        return _json_response(jsonify, {"available": True, "results": payload, "path": str(path)})

    @app.get("/api/diagnostics/report")
    def diagnostics_report():
        """摘要：导出不含密钥和提示词原文的本地诊断 JSON。"""
        health_payload = _health_checker_for(runtime).run_all()
        benchmark_path = runtime.paths.root / "benchmark_results.json"
        benchmark_payload: dict[str, Any] = {}
        if benchmark_path.is_file():
            try:
                benchmark_payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                benchmark_payload = {"error": "invalid_report"}
        return _json_response(
            jsonify,
            {
                "format": "offline-companion-diagnostics",
                "version": 1,
                "status": {
                    "app_version": __version__,
                    "backend_mode": runtime.backend_mode,
                    "privacy_mode": runtime.privacy_mode.value,
                    "local_available": runtime.local_available,
                    "cloud_available": runtime.cloud_available,
                },
                "health": health_payload,
                "benchmarks": benchmark_payload,
            },
        )

    @app.get("/api/crash-report/pending")
    def pending_crash_report():
        pending = pending_crash_payload()
        if pending is None:
            return _json_response(jsonify, {"has_crash": False})
        return _json_response(
            jsonify,
            {
                "has_crash": True,
                "content": pending["content"],
            },
        )

    @app.post("/api/crash-report/dismiss")
    def dismiss_crash_report():
        archived = archive_pending_crash("archived")
        return _json_response(
            jsonify,
            {"ok": True, "archived": archived is not None},
        )

    @app.post("/api/crash-report/submit")
    def submit_crash_report():
        submitted = archive_pending_crash("submitted")
        return _json_response(
            jsonify,
            {
                "ok": True,
                "submitted": submitted is not None,
                "outbound_sent": False,
            },
        )

    @app.get("/api/settings")
    def settings():
        canonical = get_all(runtime.paths.root)
        return _json_response(
            jsonify,
            {
                "settings": load_settings(runtime.paths.root),
                "data": canonical,
                "data_root": str(runtime.paths.root),
                "settings_path": str(runtime.paths.root / "settings.json"),
            },
        )

    @app.get("/api/settings/<module>")
    def settings_module(module: str):
        value = get_module(runtime.paths.root, module)
        if value is None:
            return _json_response(jsonify, {"error": "unknown_settings_module"}, status=404)
        return _json_response(jsonify, {"ok": True, "data": value})

    @app.patch("/api/settings/<module>")
    def patch_settings_module(module: str):
        data = request.get_json(silent=True)
        if data is None or not isinstance(data, dict):
            return _json_response(jsonify, {"error": "invalid_settings_patch"}, status=400)
        try:
            value = patch_module(runtime.paths.root, module, data)
        except KeyError:
            return _json_response(jsonify, {"error": "unknown_settings_module"}, status=404)
        except (TypeError, ValueError) as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        return _json_response(jsonify, {"ok": True, "data": value})

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
            sync_backend_mode()
        runtime.improve_plan_enabled = bool(saved.get("improve_plan_enabled", False))
        runtime.memory_on = bool(saved.get("memory_enabled", runtime.memory_on))
        if runtime.idle_detector is not None:
            try:
                runtime.idle_detector.set_threshold(float(saved.get("idle_threshold_seconds", 300)))
            except (TypeError, ValueError):
                pass
            if bool(saved.get("idle_think_enabled", True)):
                runtime.idle_detector.start()
            else:
                runtime.idle_detector.stop()
        model_state["auto"] = bool(saved.get("auto_router_enabled", model_state["auto"]))
        return _json_response(
            jsonify,
            {
                "ok": True,
                "settings": saved,
                "data": get_all(runtime.paths.root),
                "data_root": str(runtime.paths.root),
                "settings_path": str(runtime.paths.root / "settings.json"),
            },
        )

    def onboarding_payload() -> dict[str, Any]:
        """摘要：构造首次引导状态及当前可用后端摘要。"""
        settings = load_settings(runtime.paths.root)
        raw = settings.get("onboarding")
        onboarding = raw if isinstance(raw, dict) else {}
        has_onboarding_state = False
        try:
            raw_settings = json.loads((runtime.paths.root / "settings.json").read_text(encoding="utf-8"))
            has_onboarding_state = isinstance(raw_settings, dict) and "onboarding" in raw_settings
        except (OSError, TypeError, ValueError):
            pass
        backup_path = runtime.paths.root / "settings.v1.bak.json"
        if has_onboarding_state and backup_path.exists():
            try:
                legacy_settings = json.loads(backup_path.read_text(encoding="utf-8"))
                has_onboarding_state = isinstance(legacy_settings, dict) and "onboarding" in legacy_settings
            except (OSError, TypeError, ValueError):
                pass
        legacy_model_active = bool(str(settings.get("active_model_id") or "").strip())
        try:
            step = int(onboarding.get("step", 0) or 0)
        except (TypeError, ValueError):
            step = 0
        directory = ModelDirectory(runtime.paths.root)
        return {
            "completed": bool(onboarding.get("completed")) if has_onboarding_state else legacy_model_active,
            "step": max(0, min(3, step)),
            "skipped_model": bool(onboarding.get("skipped_model", False)),
            "has_local_model": bool(directory.list_local_models()),
            "has_cloud": bool(runtime.cloud_available),
            "privacy_mode": runtime.privacy_mode.value,
        }

    @app.get("/api/onboarding/state")
    def onboarding_state():
        """摘要：返回首次引导当前状态。"""
        return _json_response(jsonify, onboarding_payload())

    @app.post("/api/onboarding/complete")
    def complete_onboarding():
        """摘要：标记首次引导完成。"""
        skipped_model = onboarding_payload()["skipped_model"]
        saved = update_settings(
            runtime.paths.root,
            {"onboarding": {"completed": True, "step": 3, "skipped_model": skipped_model}},
        )
        return _json_response(jsonify, {"ok": True, "onboarding": saved["onboarding"]})

    @app.post("/api/onboarding/skip")
    def skip_onboarding():
        """摘要：跳过首次引导并记录跳过模型选择。"""
        saved = update_settings(
            runtime.paths.root,
            {"onboarding": {"completed": True, "step": 3, "skipped_model": True}},
        )
        return _json_response(jsonify, {"ok": True, "onboarding": saved["onboarding"]})

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
        sync_backend_mode()
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
        current_persona_id = runtime.orchestrator.session_core.persona.persona_id
        if not any(item["id"] == current_persona_id for item in items):
            snapshot = runtime.session_context_provider.capture().snapshot.payload
            items.append(
                {
                    "id": current_persona_id,
                    "name": str(snapshot["name"]),
                    "avatar": str(snapshot["name"])[:1],
                    "desc": "历史会话人格快照",
                    "ocean": list(snapshot["ocean"]),
                    "traits": [],
                    "anchor": str(snapshot["effective_system_prompt"]),
                    "active": False,
                }
            )
        for item in items:
            item["current"] = item["id"] == current_persona_id
        return _json_response(jsonify, {"items": items, "total": len(items)})

    @app.post("/api/personas")
    def create_persona():
        data = request.get_json(silent=True) or {}
        try:
            item = create_persisted_persona(runtime.orchestrator.conn, data)
        except ValueError as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        return _json_response(jsonify, {"ok": True, "id": item["id"], "persona": item}, status=201)

    @app.put("/api/personas/<persona_id>")
    def update_persona(persona_id: str):
        data = request.get_json(silent=True) or {}
        try:
            item = update_persisted_persona(runtime.orchestrator.conn, persona_id, data)
        except ValueError as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        if item is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        return _json_response(jsonify, {"ok": True, "persona": item})

    @app.delete("/api/personas/<persona_id>")
    def delete_persona(persona_id: str):
        try:
            deleted = delete_persisted_persona(runtime.orchestrator.conn, persona_id)
        except ValueError as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=409)
        if not deleted:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        return _json_response(jsonify, {"ok": True, "deleted": persona_id})

    @app.post("/api/personas/<persona_id>/activate")
    def activate_persona(persona_id: str):
        data = request.get_json(silent=True) or {}
        request_id = str(data.get("switch_request_id") or "").strip()
        try:
            expected_revision = int(data.get("expected_revision"))
        except (TypeError, ValueError):
            context = runtime.session_context_provider.capture()
            return _json_response(
                jsonify,
                {
                    "error": "expected_revision_required",
                    "state_unchanged": True,
                    "canonical_session_id": context.session_id,
                    "revision": context.revision,
                },
                status=400,
            )
        if not model_lock.acquire(blocking=False):
            context = runtime.session_context_provider.capture()
            return _json_response(
                jsonify,
                {
                    "error": "session_busy",
                    "state_unchanged": True,
                    "canonical_session_id": context.session_id,
                    "revision": context.revision,
                },
                status=409,
            )
        try:
            result = runtime.session_binding_service.switch_persona(
                persona_id,
                switch_request_id=request_id,
                expected_revision=expected_revision,
            )
        except SessionBindingError as exc:
            payload = {
                "error": exc.code,
                "state_unchanged": exc.state_unchanged,
                "canonical_session_id": exc.canonical_session_id,
                "revision": exc.revision,
            }
            return _json_response(jsonify, payload, status=exc.status)
        finally:
            model_lock.release()
        item = next(item for item in list_personas(runtime.orchestrator.conn) if item["id"] == persona_id)
        context = result.context
        return _json_response(
            jsonify,
            {
                "ok": True,
                "switch_request_id": result.switch_request_id,
                "previous_session_id": result.previous_session_id,
                "canonical_session_id": context.session_id,
                "revision": context.revision,
                "persona_snapshot_schema": context.snapshot.schema,
                "persona_snapshot_sha256": context.snapshot.sha256,
                "created_new_session": result.created_new_session,
                "idempotent_replay": result.idempotent_replay,
                "persona": item,
            },
        )

    @app.get("/api/models")
    def models():
        items = [_model_payload(model, runtime, model_state) for model in _visible_model_descriptors(runtime)]
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

    def model_downloader() -> ModelDownloader:
        """摘要：获取当前桌面会话共享的模型下载器。"""
        downloader = getattr(runtime, "model_downloader", None)
        if downloader is None:
            manager = getattr(runtime, "event_stream_manager", None)
            stream = manager.get(runtime.session_id) if manager is not None else None
            downloader = ModelDownloader(BUILTIN_MODELS, ModelDirectory(runtime.paths.root), stream)
            runtime.model_downloader = downloader
            downloader.cleanup_stale_temp_files()
        return downloader

    @app.post("/api/models/download")
    def download_model():
        """摘要：后台启动模型下载，重复请求返回当前进度。"""
        data = request.get_json(silent=True) or {}
        model_id = str(data.get("model_id") or "").strip()
        if not any(entry.model_id == model_id for entry in BUILTIN_MODELS):
            return _json_response(jsonify, {"error": "model_not_found"}, status=404)
        downloader = model_downloader()
        current = downloader.get_progress(model_id)
        if current is not None and current.state in {
            DownloadState.PENDING,
            DownloadState.DOWNLOADING,
            DownloadState.VERIFYING,
        }:
            return _json_response(jsonify, _download_progress_payload(current))
        download_activation_pending.add(model_id)
        try:
            future = download_executor.submit(run_model_download, model_id)
        except RuntimeError:
            download_activation_pending.discard(model_id)
            return _json_response(jsonify, {"error": "download_executor_unavailable"}, status=503)
        download_futures[model_id] = future
        return _json_response(
            jsonify,
            {"download_id": model_id, "model_id": model_id, "status": DownloadState.PENDING.value},
            status=202,
        )

    @app.post("/api/models/download/cancel")
    def cancel_model_download():
        """摘要：请求取消指定模型的后台下载。"""
        data = request.get_json(silent=True) or {}
        model_id = str(data.get("model_id") or "").strip()
        downloader = model_downloader()
        current = downloader.get_progress(model_id)
        if current is None and model_id not in download_futures:
            return _json_response(jsonify, {"error": "download_not_found"}, status=404)
        if current is not None and current.state in {
            DownloadState.COMPLETED,
            DownloadState.FAILED,
            DownloadState.CANCELLED,
        }:
            return _json_response(jsonify, {"error": "download_not_active"}, status=409)
        downloader.cancel(model_id)
        return _json_response(jsonify, {"ok": True, "model_id": model_id, "status": "cancel_requested"})

    @app.get("/api/models/download/status")
    def download_status():
        """摘要：返回全部模型下载状态。"""
        downloader = model_downloader()
        items = [
            _download_progress_payload(progress)
            for entry in BUILTIN_MODELS
            if (progress := downloader.get_progress(entry.model_id)) is not None
        ]
        for item in items:
            if item["model_id"] in download_activation_pending and item["state"] == DownloadState.COMPLETED.value:
                item["state"] = DownloadState.VERIFYING.value
        return _json_response(jsonify, {"items": items, "total": len(items)})

    @app.get("/api/models/download/events")
    def download_events():
        """摘要：以 500ms 节流推送模型下载进度。"""
        model_id = str(request.args.get("model_id") or "").strip() or None
        if model_id is not None and not any(entry.model_id == model_id for entry in BUILTIN_MODELS):
            return _json_response(jsonify, {"error": "model_not_found"}, status=404)
        downloader = model_downloader()

        def generate():
            pending: list[DownloadProgress] = []
            reporters: dict[str, ThrottledProgressReporter] = {}
            while True:
                progresses = (
                    [downloader.get_progress(model_id)]
                    if model_id
                    else [downloader.get_progress(entry.model_id) for entry in BUILTIN_MODELS]
                )
                visible = [progress for progress in progresses if progress is not None]
                for progress in visible:
                    reporter = reporters.setdefault(
                        progress.model_id,
                        ThrottledProgressReporter(pending.append, interval=0.5),
                    )
                    reporter.report(progress)
                while pending:
                    yield _sse_event(_download_progress_payload(pending.pop(0)))
                if not visible and (
                    (model_id is not None and model_id not in download_futures)
                    or (model_id is None and not download_futures)
                ):
                    break
                if visible and all(
                    progress.state
                    in {DownloadState.COMPLETED, DownloadState.FAILED, DownloadState.CANCELLED}
                    for progress in visible
                ):
                    break
                time.sleep(0.1)

        return _sse_response(Response, generate())

    @app.get("/api/models/registry")
    def model_registry():
        """摘要：返回首次引导可选择的内置模型注册表。"""
        directory = ModelDirectory(runtime.paths.root)
        items = [builtin_model_payload(entry, directory) for entry in BUILTIN_MODELS]
        return _json_response(jsonify, {"items": items, "total": len(items)})

    @app.get("/api/models/local")
    def local_models():
        """摘要：返回模型目录中已下载的本地模型。"""
        directory = ModelDirectory(runtime.paths.root)
        items = [
            {
                "model_id": model_id,
                "path": str(directory.model_path(model_id)),
                "size_bytes": directory.model_path(model_id).stat().st_size,
            }
            for model_id in directory.list_local_models()
        ]
        return _json_response(jsonify, {"items": items, "total": len(items)})

    @app.post("/api/models/cloud")
    def add_cloud_model():
        data = request.get_json(silent=True) or {}
        try:
            item = create_cloud_model(runtime.paths.root, data)
        except ValueError as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        return _json_response(jsonify, {"ok": True, "id": item["id"], "model": item}, status=201)

    @app.put("/api/models/cloud/<model_id>")
    def update_cloud_model_endpoint(model_id: str):
        data = request.get_json(silent=True) or {}
        try:
            item = update_cloud_model(runtime.paths.root, model_id, data)
        except ValueError as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        if item is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        return _json_response(jsonify, {"ok": True, "model": item})

    @app.delete("/api/models/cloud/<model_id>")
    def delete_cloud_model_endpoint(model_id: str):
        if not delete_cloud_model(runtime.paths.root, model_id):
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        if model_state.get("active") == model_id:
            set_active_model(None)
        return _json_response(jsonify, {"ok": True, "deleted": model_id})

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
                    set_active_model(model_id)
                    return _json_response(
                        jsonify,
                        {"ok": True, "active_model_id": model_state.get("active"), "enabled": True, "reloaded": False},
                    )
                return _json_response(jsonify, {"error": "not_found"}, status=404)
            payload = _model_payload(model, runtime, model_state)
            if payload["type"] == "cloud":
                # 切到云端模型时有意保留本地 backend 常驻，便于快速切回本地模型。
                set_active_model(model_id)
                runtime.active_cloud_model_id = model_id
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
            runtime.local_available = True
            runtime.local_error = None
            sync_backend_mode()
            stop = getattr(old_backend, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    logger.warning("old backend stop failed after model swap", exc_info=True)
            set_active_model(model_id)
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
        runtime.orchestrator.auto_mode_enabled = bool(model_state["auto"])
        update_settings(runtime.paths.root, {"auto_router_enabled": bool(model_state["auto"])})
        return _json_response(jsonify, {"ok": True, "auto": bool(model_state["auto"])})

    @app.get("/api/extensions")
    def extensions():
        items = _extension_payloads(plugin_gateway, runtime, extension_state)
        return _json_response(jsonify, {"items": items, "total": len(items)})

    @app.post("/api/extensions/install")
    def install_extension_endpoint():
        data = request.get_json(silent=True) or {}
        source_path = str(data.get("source_path") or "").strip()
        if not source_path:
            return _json_response(jsonify, {"error": "invalid_source_path"}, status=400)
        try:
            result = install_local_extension(runtime.paths.root, runtime.paths.db_path, Path(source_path))
        except FileNotFoundError:
            return _json_response(jsonify, {"error": "invalid_source_path"}, status=400)
        except SkillManifestError as exc:
            return _json_response(jsonify, {"error": "manifest_validation_failed", "detail": str(exc)}, status=400)
        except SkillSupplyChainError as exc:
            return _json_response(jsonify, {"error": "supply_chain_verification_failed", "detail": str(exc)}, status=403)
        except ExtensionAlreadyInstalledError as exc:
            return _json_response(jsonify, {"error": "extension_already_installed", "name": str(exc)}, status=409)
        extension_state[result["id"]] = True
        save_extension_status(runtime.paths.db_path, result["id"], True)
        return _json_response(jsonify, result, status=201)

    @app.post("/api/extensions/<extension_id>/toggle")
    def toggle_extension(extension_id: str):
        data = request.get_json(silent=True) or {}
        extension_state[extension_id] = bool(data.get("enabled", True))
        save_extension_status(runtime.paths.db_path, extension_id, extension_state[extension_id])
        return _json_response(jsonify, {"ok": True, "id": extension_id, "enabled": extension_state[extension_id]})

    @app.delete("/api/extensions/<extension_id>")
    def uninstall_extension_endpoint(extension_id: str):
        try:
            result = uninstall_local_extension(runtime.paths.root, runtime.paths.db_path, extension_id)
        except ExtensionNotInstalledError:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        except SkillInvocationError as exc:
            return _json_response(jsonify, {"error": "extension_running", "detail": str(exc)}, status=409)
        extension_state.pop(extension_id, None)
        return _json_response(jsonify, result)

    @app.get("/api/plugins")
    def plugins():
        return _json_response(jsonify, {"items": plugin_gateway.list_plugins()})

    def annotation_session() -> AnnotationSession:
        """摘要：获取当前桌面进程内的临时标注会话。"""
        session = getattr(runtime, "_annotation_session", None)
        if session is None:
            session = AnnotationSession()
            runtime._annotation_session = session
        return session

    @app.post("/api/ui_annotation/screenshot")
    def annotation_screenshot():
        """摘要：截取本地屏幕并以 base64 返回，不写入持久化存储。"""
        try:
            import mss
            import mss.tools
        except ImportError:
            return _json_response(jsonify, {"error": "screenshot_dependency_unavailable"}, status=503)
        try:
            with mss.mss() as capture:
                monitor = capture.monitors[1]
                image = capture.grab(monitor)
                content = mss.tools.to_png(image.rgb, image.size)
        except (OSError, IndexError) as exc:
            return _json_response(jsonify, {"error": "screenshot_failed", "detail": str(exc)}, status=503)
        return _json_response(jsonify, {"content_type": "image/png", "data": base64.b64encode(content).decode("ascii")})

    @app.post("/api/ui_annotation/page")
    def annotation_page():
        data = request.get_json(silent=True) or {}
        try:
            page = annotation_session().add_page(str(data.get("name") or "页面"), data.get("page_id"))
        except AnnotationError as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        return _json_response(jsonify, {"ok": True, "page": page}, status=201)

    @app.post("/api/ui_annotation/element")
    def annotation_element():
        data = request.get_json(silent=True) or {}
        try:
            element = annotation_session().add_element(
                str(data.get("page_id") or ""),
                data.get("region") or [],
                str(data.get("target_text") or ""),
                str(data.get("type") or "display"),
                data.get("element_id"),
            )
        except (AnnotationError, TypeError, ValueError) as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        return _json_response(jsonify, {"ok": True, "element": element}, status=201)

    @app.post("/api/ui_annotation/transition")
    def annotation_transition():
        data = request.get_json(silent=True) or {}
        try:
            transition = annotation_session().add_transition(
                str(data.get("from_page") or ""), str(data.get("to_page") or ""), str(data.get("trigger_element_id") or "")
            )
        except AnnotationError as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        return _json_response(jsonify, {"ok": True, "transition": transition})

    @app.post("/api/ui_annotation/generate_features")
    def annotation_generate_features():
        data = request.get_json(silent=True) or {}
        annotation_session().generate_features(data.get("page_texts") or {})
        return _json_response(jsonify, {"ok": True, "pages": annotation_session().pages})

    @app.post("/api/ui_annotation/export")
    def annotation_export():
        data = request.get_json(silent=True) or {}
        try:
            target = annotation_session().export(runtime.paths.root, data.get("skill_name", ""), data.get("app_name", ""))
        except (AnnotationError, OSError) as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        return _json_response(jsonify, {"ok": True, "path": str(target)})

    @app.get("/api/plugins/config")
    def plugin_config():
        """摘要：返回声明式插件配置及当前 Fiber 状态。"""
        loader = getattr(runtime, "plugin_loader", None)
        if loader is None:
            return _json_response(jsonify, {"config": None, "plugins": [], "source": "not_loaded"})
        return _json_response(jsonify, loader.dump_config())

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

    @app.get("/api/memory/events")
    def semantic_events():
        """摘要：列出可由用户管理的 active 语义事件。"""
        repo = EventRepository(runtime.orchestrator.conn)
        event_type = request.args.get("type", "").strip()
        events = repo.get_by_type(event_type, limit=200) if event_type else repo.get_active(limit=200)
        return _json_response(jsonify, [_semantic_event_row(event) for event in events])

    @app.post("/api/memory/events")
    def create_semantic_event():
        """摘要：手动创建一条语义事件并生成内容向量。"""
        data = request.get_json(silent=True) or {}
        content = str(data.get("content") or "").strip()
        if not content:
            return _json_response(jsonify, {"error": "missing content"}, status=400)
        embedder = _semantic_embed(runtime)
        content_embedding = embedder(content)
        event = SemanticEvent(
            event_id=uuid.uuid4().hex,
            event_type=str(data.get("event_type") or "fact"),
            subject=str(data.get("subject") or "user"),
            content=content,
            content_embedding=content_embedding,
            content_embedding_space=embedding_space_of(embedder),
            emotional_valence=float(data.get("emotional_valence", 0.0)),
            emotional_arousal=float(data.get("emotional_arousal", 0.0)),
            importance=float(data.get("importance", 2.0)),
            temporal_marker="manual",
            created_at=time.time(),
        )
        try:
            repo = EventRepository(runtime.orchestrator.conn)
            repo.store(event)
        except (TypeError, ValueError) as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        return _json_response(jsonify, _semantic_event_row(event), status=201)

    @app.patch("/api/memory/events/<event_id>")
    def patch_semantic_event(event_id: str):
        """摘要：更新用户可编辑的语义事件字段。"""
        data = request.get_json(silent=True) or {}
        repo = EventRepository(runtime.orchestrator.conn)
        try:
            changed = repo.update_fields(event_id, data)
        except (TypeError, ValueError) as exc:
            return _json_response(jsonify, {"error": str(exc)}, status=400)
        event = repo.get(event_id)
        if event is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        return _json_response(jsonify, {"ok": changed, "item": _semantic_event_row(event)})

    @app.delete("/api/memory/events/<event_id>")
    def delete_semantic_event(event_id: str):
        """摘要：软删除语义事件，保留事件审计记录。"""
        repo = EventRepository(runtime.orchestrator.conn)
        event = repo.get(event_id)
        if event is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        repo.mark_dormant(event_id)
        return _json_response(jsonify, {"ok": True})

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

    @app.get("/api/sessions/current")
    def current_session():
        """摘要：返回 SQLite canonical 会话及其快照证明，供未知状态对账。"""
        try:
            context = runtime.session_binding_service.current()
        except SessionBindingError as exc:
            return _json_response(
                jsonify,
                {"error": exc.code, "state_unchanged": False},
                status=exc.status,
            )
        persona_id = context.session_core.persona.persona_id
        item = next(
            (candidate for candidate in list_personas(runtime.orchestrator.conn) if candidate["id"] == persona_id),
            {
                "id": persona_id,
                "name": context.session_core.persona.name,
                "active": False,
            },
        )
        return _json_response(
            jsonify,
            {
                "ok": True,
                "canonical_session_id": context.session_id,
                "revision": context.revision,
                "persona_snapshot_schema": context.snapshot.schema,
                "persona_snapshot_sha256": context.snapshot.sha256,
                "persona": item,
            },
        )

    @app.get("/api/sessions/<session_id>/messages")
    def session_messages(session_id: str):
        rows = runtime.orchestrator.conn.execute(
            """
            SELECT id, role, content, emotion, created_at, meta_json, status
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
                "status": row["status"],
            }
            for msg_idx, row in enumerate(rows)
        ]
        return _json_response(jsonify, {"session_id": session_id, "items": items, "total": len(items)})

    @app.get("/api/sessions/<session_id>/events")
    def session_events(session_id: str):
        """摘要：返回指定序号之后的持久化 SSE 事件，供断线缺口修复。"""
        from_seq = max(0, request.args.get("from_seq", default=0, type=int) or 0)
        events = stream_events_after(runtime.orchestrator.conn, session_id, from_seq)
        return _json_response(
            jsonify,
            {
                "session_id": session_id,
                "events": events,
                "latest_seq": latest_stream_event_seq(runtime.orchestrator.conn, session_id),
            },
        )

    @app.get("/api/trajectory/<stream_id>")
    def trajectory(stream_id: str):
        """摘要：返回开发模式 Trajectory 投影，不改变事件源。"""
        manager = getattr(runtime, "event_stream_manager", None)
        stream = manager.get(stream_id) if manager is not None else None
        if stream is None:
            return _json_response(jsonify, {"timeline": [], "summary": {"event_count": 0}})
        trace_id = request.args.get("trace_id", type=str) or None
        return _json_response(jsonify, TRAJECTORY_PROJECTION.project(stream.get_events(), trace_id))

    @app.get("/api/decomp-samples")
    def list_decomposition_samples():
        """摘要：列出本地任务拆解范例，默认仅展示候选与已验证样本。"""
        repository = runtime.sample_repository
        if repository is None:
            return _json_response(
                jsonify,
                {"items": [], "total": 0, "limit": 100, "offset": 0, "has_more": False},
            )
        state = str(request.args.get("state") or "").strip()
        try:
            limit = max(1, min(int(request.args.get("limit", 100)), 500))
            offset = max(0, int(request.args.get("offset", 0)))
        except (TypeError, ValueError):
            return _json_response(jsonify, {"error": "invalid_pagination"}, status=400)
        try:
            if state and state != "all":
                states = (state,)
            else:
                states = () if state == "all" else (
                    SampleState.CANDIDATE.value,
                    SampleState.VERIFIED.value,
                )
            samples = repository.list_samples(sample_states=states, limit=limit, offset=offset)
            total = repository.count_samples(sample_states=states)
        except ValueError:
            return _json_response(jsonify, {"error": "invalid_state"}, status=400)
        items = [_decomposition_sample_payload(sample) for sample in samples]
        return _json_response(
            jsonify,
            {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(items) < total,
            },
        )

    @app.get("/api/decomp-samples/<sample_id>")
    def get_decomposition_sample(sample_id: str):
        """摘要：返回单条任务拆解范例详情。"""
        sample = _find_decomposition_sample(runtime, sample_id)
        if sample is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        return _json_response(jsonify, {"sample": _decomposition_sample_payload(sample)})

    @app.put("/api/decomp-samples/<sample_id>")
    def edit_decomposition_sample(sample_id: str):
        """摘要：编辑任务描述与步骤，并将结果确认为用户范例。"""
        lifecycle = runtime.sample_lifecycle
        if lifecycle is None or _find_decomposition_sample(runtime, sample_id) is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        data = request.get_json(silent=True) or {}
        try:
            sample = lifecycle.edit(
                sample_id,
                task_description=str(data.get("task_description") or ""),
                steps=data.get("steps") if isinstance(data.get("steps"), list) else [],
            )
        except ValueError as exc:
            return _json_response(jsonify, {"error": "invalid_sample", "detail": str(exc)}, status=400)
        return _json_response(jsonify, {"ok": True, "sample": _decomposition_sample_payload(sample)})

    @app.delete("/api/decomp-samples/<sample_id>")
    def delete_decomposition_sample(sample_id: str):
        """摘要：永久删除任务拆解范例，不保留软删除记录。"""
        repository = runtime.sample_repository
        if repository is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        try:
            deleted = repository.delete(sample_id)
        except ValueError:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        if not deleted:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        return _json_response(jsonify, {"ok": True, "deleted_sample_id": str(sample_id)})

    @app.post("/api/decomp-samples/<sample_id>/verify")
    def verify_decomposition_sample(sample_id: str):
        """摘要：把样本确认为用户权威范例。"""
        return _transition_decomposition_sample(runtime, jsonify, sample_id, "verify")

    @app.post("/api/decomp-samples/<sample_id>/reject")
    def reject_decomposition_sample(sample_id: str):
        """摘要：由用户丢弃样本。"""
        return _transition_decomposition_sample(runtime, jsonify, sample_id, "reject")

    @app.post("/api/decomp-samples/<sample_id>/restore")
    def restore_decomposition_sample(sample_id: str):
        """摘要：由用户恢复已丢弃、陈旧或归档样本。"""
        return _transition_decomposition_sample(runtime, jsonify, sample_id, "restore")

    @app.post("/api/plans/<plan_id>/save-as-sample")
    def save_plan_as_decomposition_sample(plan_id: str):
        """摘要：将终态计划按计划快照幂等保存为用户权威范例。"""
        plan_orchestrator = runtime.plan_orchestrator or _fallback_plan_orchestrator(runtime)
        context = plan_orchestrator.load_context(plan_id)
        lifecycle = runtime.sample_lifecycle
        if context is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        if lifecycle is None:
            return _json_response(jsonify, {"error": "sample_library_unavailable"}, status=503)
        if not context.is_terminal():
            return _json_response(jsonify, {"error": "plan_not_terminal"}, status=409)
        decomposition = context.context_vars.get("decomposition")
        if not isinstance(decomposition, dict):
            decomposition = {}
            context.context_vars["decomposition"] = decomposition
        candidate_sample_id = str(decomposition.get("candidate_sample_id") or "").strip()
        existing = _find_decomposition_sample(runtime, candidate_sample_id) if candidate_sample_id else None
        if existing is not None:
            return _json_response(
                jsonify,
                {"ok": True, "created": False, "sample": _decomposition_sample_payload(existing)},
            )
        manual_plan = context.context_vars.get("manual_plan")
        goal = str(manual_plan.get("goal") or "").strip() if isinstance(manual_plan, dict) else ""
        if not goal:
            goal = str(context.context_vars.get("goal") or context.context_vars.get("user_input") or "").strip()
        if not goal:
            return _json_response(jsonify, {"error": "missing_goal"}, status=409)
        provenance_ids = decomposition.get("sample_ids")
        sample = lifecycle.create_candidate(
            goal,
            context.steps.values(),
            source="user_edit",
            plan_id=context.plan_id,
            provenance_sample_ids=provenance_ids if isinstance(provenance_ids, list) else (),
        )
        sample = lifecycle.confirm(sample.sample_id)
        decomposition["candidate_sample_id"] = sample.sample_id
        plan_orchestrator.save_context(context)
        return _json_response(
            jsonify,
            {"ok": True, "created": True, "sample": _decomposition_sample_payload(sample)},
            status=201,
        )

    @app.post("/api/plan/decompose")
    def decompose_plan():
        data = request.get_json(silent=True) or {}
        goal = str(data.get("goal") or data.get("message") or "").strip()
        if not goal:
            return _json_response(jsonify, {"error": "missing goal"}, status=400)
        plan_orchestrator = runtime.plan_orchestrator or _fallback_plan_orchestrator(runtime)
        steps = plan_orchestrator.decide(goal)
        if isinstance(steps, NotDecomposableResult):
            payload = {"ok": True, "status": steps.status, "reason": steps.reason}
            if steps.fallback_notice:
                payload["fallback_notice"] = steps.fallback_notice
            return _json_response(
                jsonify,
                payload,
            )
        plan = _steps_to_legacy_plan(
            goal,
            steps,
            skill_name=plan_orchestrator._skill_name,
            skill_stages=plan_orchestrator._skill_stages,
        )
        context = plan_orchestrator.create_plan(str(plan["id"]), steps)
        context.context_vars["manual_plan"] = {
            "goal": goal,
            "skill_name": plan_orchestrator._skill_name,
            "skill_stages": list(plan_orchestrator._skill_stages),
            "created_at": plan["created_at"],
        }
        context.context_vars["session_id"] = runtime.session_id
        context.context_vars["original_input"] = goal
        if plan_orchestrator._skill_name:
            context.context_vars["skill_name"] = plan_orchestrator._skill_name
            context.context_vars["skill_stages"] = list(plan_orchestrator._skill_stages)
        plan_orchestrator.save_context(context)
        plan = _manual_plan_projection(context)
        plan = _save_manual_plan(runtime.orchestrator.conn, plan)
        user_message_id = append_message(
            runtime.orchestrator.conn,
            runtime.session_id,
            "user",
            goal,
            meta={"channel": "manual_plan", "plan_id": context.plan_id},
        )
        context.context_vars["manual_plan_user_message_id"] = user_message_id
        plan_orchestrator.save_context(context)
        return _json_response(jsonify, {"ok": True, "plan": plan}, status=201)

    @app.get("/api/plan/<plan_id>/status")
    def plan_status(plan_id: str):
        """摘要：返回任务步骤与可渲染的进度摘要。"""
        plan_orchestrator = runtime.plan_orchestrator or _fallback_plan_orchestrator(runtime)
        context = plan_orchestrator.load_context(plan_id)
        plan = _manual_plan_projection(context) if context is not None else get_plan(runtime.orchestrator.conn, plan_id)
        if plan is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        if context is not None:
            plan = _save_manual_plan(runtime.orchestrator.conn, plan)
        steps = list(plan.get("steps") or [])
        completed = sum(1 for step in steps if step.get("status") in {"done", "completed", "skipped"})
        current = next(
            (step for step in steps if step.get("status") in {"running", "consent"}),
            None,
        )
        return _json_response(
            jsonify,
            {
                "plan_id": plan_id,
                "status": plan.get("status", "pending"),
                "steps": steps,
                "current_step": current,
                "completed_steps": completed,
                "total_steps": len(steps),
                "progress_percent": round(completed / len(steps) * 100) if steps else 0,
            },
        )

    @app.post("/api/plan/<plan_id>/execute")
    def execute_plan_step(plan_id: str):
        data = request.get_json(silent=True) or {}
        timeout_seconds = _coerce_timeout(data.get("timeout"), default=20.0)
        step_id = data.get("step_id")
        plan_orchestrator = runtime.plan_orchestrator or _fallback_plan_orchestrator(runtime)
        context = plan_orchestrator.load_context(plan_id)
        if context is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        plan = _manual_plan_projection(context)
        step = _next_executable_step(plan) if step_id is None else _find_plan_step(plan, int(step_id))
        if step is None:
            plan["status"] = "done" if all(s["status"] == "done" for s in plan["steps"]) else plan["status"]
            plan = _update_manual_plan(runtime.orchestrator.conn, plan)
            payload = {"ok": True, "status": plan["status"], "plan": plan}
            final_reply = _manual_plan_final_reply(runtime, context, plan_orchestrator)
            if final_reply is not None:
                payload["final_reply"] = final_reply
            return _json_response(jsonify, payload)
        consent_request_id = str(data.get("consent_request_id") or "").strip()
        context_step_id = _manual_context_step_id(context, int(step["id"]))
        if consent_request_id:
            if not _is_plan_consent_allowed(runtime, consent_request_id):
                context.step_status[context_step_id] = CoreStepStatus.SKIPPED
                context.step_errors.pop(context_step_id, None)
                context.mark_dependency_satisfied(context_step_id)
                context.mark_processed(context_step_id)
                context.status = CorePlanStatus.PAUSED
                context.paused_reason = "consent_declined"
                context.paused_step_id = context_step_id
                plan_orchestrator.save_context(context)
                plan = _manual_plan_projection(context)
                plan = _update_manual_plan(runtime.orchestrator.conn, plan)
                step = _find_plan_step(plan, int(step["id"])) or step
                return _json_response(
                    jsonify,
                    {
                        "ok": True,
                        "status": "declined",
                        "message": CONSENT_DECLINED_MESSAGE,
                        "plan": plan,
                        "step": step,
                    },
                )
            context.step_status[context_step_id] = CoreStepStatus.READY
            context.status = CorePlanStatus.RUNNING
            context.paused_reason = None
            context.paused_step_id = None
            context.context_vars["requires_consent"] = False
        elif step.get("requires_auth") and not bool(data.get("consent_granted", False)):
            request_id = _submit_plan_consent(runtime, plan, step)
            context.step_status[context_step_id] = CoreStepStatus.BLOCKED
            context.status = CorePlanStatus.PAUSED
            context.paused_reason = PlanErrorCode.WAITING_CONSENT.value
            context.paused_step_id = context_step_id
            context.set_step_consent_request(context_step_id, {"request_id": request_id})
            context.context_vars["requires_consent"] = True
            plan_orchestrator.save_context(context)
            plan = _manual_plan_projection(context)
            plan = _update_manual_plan(runtime.orchestrator.conn, plan)
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
            context.step_status[context_step_id] = CoreStepStatus.FAILED
            context.step_errors[context_step_id] = "步骤超时，可重试或跳过。"
            context.status = CorePlanStatus.PAUSED
            context.paused_reason = "timeout"
            context.paused_step_id = context_step_id
            plan_orchestrator.save_context(context)
            plan = _manual_plan_projection(context)
            plan = _update_manual_plan(runtime.orchestrator.conn, plan)
            step = _find_plan_step(plan, int(step["id"])) or step
            return _json_response(
                jsonify,
                {"ok": False, "error": "timeout", "status": "timeout", "plan": plan, "step": step},
                status=408,
            )
        context = plan_orchestrator.execute_next(context, invoke_skill=_legacy_plan_step_invoker)
        plan = _manual_plan_projection(context)
        plan = _update_manual_plan(runtime.orchestrator.conn, plan)
        if context.paused_reason == PlanErrorCode.HARD_GATE_BLOCKED.value:
            blocked_step_id = list(context.steps).index(context.paused_step_id) if context.paused_step_id else None
            step = _find_plan_step(plan, blocked_step_id) if blocked_step_id is not None else step
            return _json_response(
                jsonify,
                {
                    "ok": False,
                    "error": PlanErrorCode.HARD_GATE_BLOCKED.value,
                    "status": PlanErrorCode.HARD_GATE_BLOCKED.value,
                    "missing_stages": context.context_vars.get("hard_gate", {}).get("missing_stages", []),
                    "message": _hard_gate_message(context),
                    "plan": plan,
                    "step": step,
                },
                status=409,
            )
        step = _find_plan_step(plan, int(step["id"])) or step
        final_reply = _manual_plan_final_reply(runtime, context, plan_orchestrator)
        if context.status is CorePlanStatus.FAILED:
            payload = {
                "ok": False,
                "error": context.error or "step_failed",
                "status": "failed",
                "plan": plan,
                "step": step,
            }
            if final_reply is not None:
                payload["final_reply"] = final_reply
            return _json_response(
                jsonify,
                payload,
                status=500,
            )
        payload = {"ok": True, "status": step["status"], "plan": plan, "step": step}
        if final_reply is not None:
            payload["final_reply"] = final_reply
        return _json_response(jsonify, payload)

    @app.post("/api/plan/<plan_id>/pause")
    def pause_plan(plan_id: str):
        plan_orchestrator = runtime.plan_orchestrator or _fallback_plan_orchestrator(runtime)
        context = plan_orchestrator.pause(plan_id, reason="manual_pause")
        if context is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        plan = _manual_plan_projection(context)
        plan = _update_manual_plan(runtime.orchestrator.conn, plan)
        return _json_response(jsonify, {"ok": True, "plan": plan})

    @app.post("/api/plan/<plan_id>/resume")
    def resume_plan(plan_id: str):
        plan_orchestrator = runtime.plan_orchestrator or _fallback_plan_orchestrator(runtime)
        context = plan_orchestrator.load_context(plan_id)
        if context is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        if not context.is_terminal():
            context.status = CorePlanStatus.RUNNING
            context.paused_reason = None
            context.paused_step_id = None
            plan_orchestrator.save_context(context)
        plan = _manual_plan_projection(context)
        plan = _update_manual_plan(runtime.orchestrator.conn, plan)
        return _json_response(jsonify, {"ok": True, "plan": plan})

    @app.post("/api/plan/<plan_id>/cancel")
    def cancel_plan(plan_id: str):
        plan_orchestrator = runtime.plan_orchestrator or _fallback_plan_orchestrator(runtime)
        context = plan_orchestrator.load_context(plan_id)
        if context is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        plan_orchestrator.cancel(plan_id)
        context = plan_orchestrator.load_context(plan_id)
        if context is None:
            return _json_response(jsonify, {"error": "not_found"}, status=404)
        plan = _manual_plan_projection(context)
        final_reply = _manual_plan_final_reply(runtime, context, plan_orchestrator)
        delete_plan(runtime.orchestrator.conn, plan_id)
        return _json_response(jsonify, {"ok": True, "plan": plan, "final_reply": final_reply})

    @app.post("/api/chat")
    def chat():
        data = request.get_json(silent=True) or {}
        if not model_lock.acquire(blocking=False):
            return _json_response(jsonify, {"error": "model_loading", "reply": "", "blocked": False}, status=503)
        if runtime.orchestrator.auto_mode_enabled:
            message = str(data.get("message", "")).strip()
            resume = bool(data.get("resume", False))
            plan_id = str(data.get("plan_id") or "").strip() or None
            consent_request_id = str(data.get("consent_request_id") or "").strip() or None
            base_message = BaseMessage(
                message_id=str(uuid.uuid4()),
                topic="chat.auto",
                source="shell",
                session_id=runtime.session_id,
                payload={"user_input": message},
            )

            def generate_auto():
                user_message_id = None
                try:
                    if not resume and not message:
                        yield _sse_event({"type": PlanEventName.ERROR.value, "error": "（请输入内容）", "done": True})
                        return
                    if not resume:
                        safety_result = runtime.orchestrator.check_safety(message, memory_on=runtime.memory_on)
                        if safety_result is not None:
                            yield _sse_event({"type": PlanEventName.PLAN_COMPLETE.value, **turn_result_to_payload(safety_result), "done": True})
                            return
                    if runtime.auto_turn_orchestrator is None:
                        raise RuntimeError("auto_turn_orchestrator_unavailable")
                    events = iter(runtime.auto_turn_orchestrator.execute_turn_stream(
                        base_message,
                        message,
                        plan_id=plan_id,
                        resume=resume,
                        consent_request_id=consent_request_id,
                    ))
                    first_event = next(events, None)
                    if first_event and first_event.get("type") == PlanEventName.NOT_DECOMPOSABLE.value:
                        payload = process_chat_message(runtime, message)
                        fallback_notice = str(first_event.get("fallback_notice") or "").strip()
                        if fallback_notice and payload.get("reply"):
                            payload["reply"] = f"{fallback_notice}\n\n{payload['reply']}"
                        yield _sse_event(
                            {
                                "type": "chat_fallback",
                                "reason": first_event.get("reason"),
                                "fallback_notice": fallback_notice or None,
                                **payload,
                                "done": True,
                            }
                        )
                        return
                    if not resume:
                        user_message_id = append_message(
                            runtime.orchestrator.conn,
                            runtime.session_id,
                            "user",
                            message,
                            meta={"channel": "auto"},
                        )
                    pending_events = ([first_event] if first_event is not None else [])
                    for event in chain(pending_events, events):
                        if user_message_id is not None:
                            event.setdefault("user_message_id", user_message_id)
                        if event.get("type") in {
                            PlanEventName.PLAN_COMPLETE.value,
                            PlanEventName.PLAN_FAILED.value,
                            PlanEventName.PLAN_CANCELLED.value,
                        } and event.get("reply"):
                            event["message_id"] = append_message(
                                runtime.orchestrator.conn,
                                runtime.session_id,
                                "assistant",
                                str(event["reply"]),
                                meta={"channel": "auto", "plan_id": event.get("plan_id")},
                            )
                        yield _sse_event(event)
                except Exception as exc:
                    yield _sse_event({"type": PlanEventName.ERROR.value, "error": str(exc), "done": True})
                finally:
                    model_lock.release()

            return _sse_response(Response, generate_auto())
        if bool(data.get("stream", False)):
            message = str(data.get("message", ""))

            def generate():
                stream = process_chat_message_stream(runtime, message)
                try:
                    for event in stream:
                        persisted_event = append_stream_event(
                            runtime.orchestrator.conn,
                            runtime.session_id,
                            event,
                        )
                        yield _sse_event(persisted_event)
                except GeneratorExit:
                    raise
                except Exception as exc:
                    error_event = append_stream_event(
                        runtime.orchestrator.conn,
                        runtime.session_id,
                        {
                            "done": True,
                            "error": str(exc),
                            "reply": "",
                            "blocked": False,
                            "memory_saved": [],
                            "memory_recall_count": 0,
                        },
                    )
                    yield _sse_event(error_event)
                finally:
                    stream.close()
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
            payload = consent_decision_payload(turn_result_to_payload(result), allowed=allowed)
            return _json_response(jsonify, payload)
        except KeyError as exc:
            gateway = getattr(runtime.orchestrator, "consent_gateway", None)
            pending = gateway.get_pending(request_id) if gateway is not None else None
            if pending is None:
                return _json_response(jsonify, {"error": str(exc)}, status=404)
            artifact = gateway.decide(request_id, allowed)
            payload = {
                "ok": True,
                "artifact": artifact,
                "consent": gateway.to_modal_payload(request_id),
            }
            if not allowed:
                consent_request = pending.consent_request
                plan_orchestrator = runtime.plan_orchestrator or _fallback_plan_orchestrator(runtime)
                context = plan_orchestrator.load_context(consent_request.plan_id)
                step_id = str(consent_request.step_id).removeprefix("step_")
                if context is not None and step_id.isdigit():
                    context_step_id = _manual_context_step_id(context, int(step_id))
                    context.step_status[context_step_id] = CoreStepStatus.SKIPPED
                    context.step_errors.pop(context_step_id, None)
                    context.mark_dependency_satisfied(context_step_id)
                    context.mark_processed(context_step_id)
                    context.status = CorePlanStatus.PAUSED
                    context.paused_reason = "consent_declined"
                    context.paused_step_id = context_step_id
                    plan_orchestrator.save_context(context)
                    plan = _manual_plan_projection(context)
                    plan = _update_manual_plan(runtime.orchestrator.conn, plan)
                    payload["plan"] = plan
                    payload["step"] = _find_plan_step(plan, int(step_id))
            return _json_response(jsonify, consent_decision_payload(payload, allowed=allowed))

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


def _download_progress_payload(progress: DownloadProgress) -> dict[str, Any]:
    """摘要：将下载进度转换为 API 与 SSE 共用的 JSON payload。"""
    return {
        "model_id": progress.model_id,
        "state": progress.state.value,
        "status": progress.state.value,
        "downloaded_bytes": progress.downloaded_bytes,
        "total_bytes": progress.total_bytes,
        "speed_bytes_per_sec": progress.speed_bytes_per_sec,
        "error": progress.error,
        "source_url": progress.source_url,
        "attempt": progress.attempt,
        "source_index": progress.source_index,
        "type": "model/download_progress",
    }


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


def _decomposition_sample_payload(sample: DecompositionSample) -> dict[str, Any]:
    """摘要：把拆解样本转换为稳定、可 JSON 序列化的桌面 API DTO。"""
    return {
        "id": sample.sample_id,
        "task_description": sample.task_description,
        "state": sample.sample_state,
        "verify_kind": sample.verify_kind,
        "steps": [dict(step) for step in sample.steps],
        "source": sample.source,
        "plan_id": sample.plan_id,
        "provenance": {"sample_ids": list(sample.provenance_sample_ids)},
        "usage": dict(sample.usage),
        "tool_refs": list(sample.tool_refs),
        "version": sample.version,
        "created_at": sample.created_at,
        "updated_at": sample.updated_at,
        "last_hit_at": sample.usage.get("last_hit_at"),
        "stale_reason": sample.stale_reason,
    }


def _find_decomposition_sample(runtime: DesktopRuntime, sample_id: str) -> DecompositionSample | None:
    """摘要：安全查找单条拆解样本，非法 ID 与不存在统一视为未找到。"""
    repository = runtime.sample_repository
    if repository is None or not str(sample_id).strip():
        return None
    try:
        return repository.get(sample_id)
    except ValueError:
        return None


def _transition_decomposition_sample(
    runtime: DesktopRuntime,
    jsonify,
    sample_id: str,
    action: str,
):
    """摘要：执行用户样本迁移，并统一映射未找到与非法迁移响应。"""
    lifecycle = runtime.sample_lifecycle
    if lifecycle is None or _find_decomposition_sample(runtime, sample_id) is None:
        return _json_response(jsonify, {"error": "not_found"}, status=404)
    operation = {
        "verify": lifecycle.confirm,
        "reject": lifecycle.reject,
        "restore": lifecycle.restore,
    }[action]
    try:
        sample = operation(sample_id)
    except InvalidSampleTransitionError:
        return _json_response(jsonify, {"error": "invalid_transition"}, status=409)
    return _json_response(jsonify, {"ok": True, "sample": _decomposition_sample_payload(sample)})


def _sse_event(payload: Any) -> str:
    """摘要：把 JSON payload 包装为一条 SSE data 事件。"""
    return f"data: {json.dumps(_json_safe(payload), ensure_ascii=False)}\n\n"


def _sse_response(response_factory: Any, generator: Any) -> Any:
    """摘要：构造禁用缓冲的 SSE 响应，确保 token 尽快 flush 到前端。"""
    response = response_factory(generator, mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
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


def _manual_context_step_id(context: TaskContext, legacy_step_id: int) -> str:
    """摘要：把前端数字步骤 ID 映射到计划快照中的真实步骤 ID。"""
    step_ids = list(context.steps)
    if legacy_step_id < 0 or legacy_step_id >= len(step_ids):
        raise ValueError(f"unknown manual plan step: {legacy_step_id}")
    return step_ids[legacy_step_id]


def _save_manual_plan(conn: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """摘要：持久化手动计划并保留仅存在于运行时快照的展示字段。"""

    return _restore_manual_plan_runtime_fields(save_plan(conn, plan), plan)


def _update_manual_plan(conn: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """摘要：更新手动计划并保留仅存在于运行时快照的展示字段。"""

    return _restore_manual_plan_runtime_fields(update_plan(conn, plan), plan)


def _restore_manual_plan_runtime_fields(
    persisted: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    """摘要：把 SQLite 旧表未持久化的计划展示字段恢复到响应。"""

    persisted["candidate_sample_id"] = projection.get("candidate_sample_id")
    return persisted


def _manual_plan_final_reply(
    runtime: DesktopRuntime,
    context: TaskContext,
    plan_orchestrator: PlanOrchestrator,
) -> str | None:
    """摘要：使用与 Auto 链相同的生成器构造手动计划终态正文。"""
    persisted = context.context_vars.get("manual_final_reply")
    if isinstance(persisted, dict):
        content = str(persisted.get("content") or "").strip()
        if content:
            return content
    auto_turn = runtime.auto_turn_orchestrator
    summarizer = getattr(auto_turn, "final_reply_summarizer", None) if auto_turn is not None else None
    reply = build_final_reply(context, summarizer=summarizer)
    if reply is None:
        return None
    message_id = append_message(
        runtime.orchestrator.conn,
        runtime.session_id,
        "assistant",
        reply,
        meta={"channel": "manual_plan", "plan_id": context.plan_id},
    )
    context.context_vars["manual_final_reply"] = {
        "content": reply,
        "message_id": message_id,
    }
    plan_orchestrator.save_context(context)
    return reply


def _manual_plan_projection(context: TaskContext) -> dict[str, Any]:
    """摘要：将唯一事实源计划快照投影为现有桌面 API 结构。"""
    metadata = context.context_vars.get("manual_plan")
    if not isinstance(metadata, dict):
        metadata = {}
    step_ids = list(context.steps)
    step_indexes = {step_id: index for index, step_id in enumerate(step_ids)}
    steps: list[dict[str, Any]] = []
    for step_id in step_ids:
        step = context.steps[step_id]
        status = context.step_status.get(step_id, CoreStepStatus.PENDING)
        status_value = status.value
        if (
            status is CoreStepStatus.BLOCKED
            and context.paused_reason == PlanErrorCode.WAITING_CONSENT.value
            and context.paused_step_id == step_id
        ):
            status_value = "consent"
        elif status is CoreStepStatus.DEGRADED:
            status_value = "done"
        elif status is CoreStepStatus.CANCELLED:
            status_value = "skipped"
        result = context.get_step_result(step_id)
        if isinstance(result, dict) and "result" in result:
            result = result["result"]
        elif result is not None and not isinstance(result, (str, int, float, bool)):
            result = str(result)
        consent_payload = context.get_step_consent_request(step_id) or {}
        projected_step = {
            "id": step_indexes[step_id],
            "title": step.title or str(step.payload.get("description") or step.skill_id),
            "description": step.description,
            "expected_output": step.expected_output,
            "verification": step.verification,
            "completion_criteria": step.completion_criteria,
            "stage": step.stage,
            "estimated_minutes": step.estimated_minutes,
            "files": list(step.files),
            "deps": [step_indexes[dependency] for dependency in step.depends_on if dependency in step_indexes],
            "risk": str(step.payload.get("risk") or ("high" if step.require_consent else "medium")),
            "requires_auth": step.require_consent,
            "status": status_value,
            "result": result,
            "error": context.step_errors.get(step_id),
        }
        if consent_payload.get("request_id"):
            projected_step["consent_request_id"] = str(consent_payload["request_id"])
        steps.append(projected_step)
    status_value = context.status.value
    if context.status is CorePlanStatus.FAILED:
        status_value = "paused"
    created_at = float(metadata.get("created_at") or context.started_at or context.updated_at or time.time())
    decomposition = context.context_vars.get("decomposition")
    candidate_sample_id = (
        str(decomposition.get("candidate_sample_id") or "").strip()
        if isinstance(decomposition, dict)
        else ""
    )
    return {
        "id": context.plan_id,
        "goal": str(metadata.get("goal") or ""),
        "status": status_value,
        "skill_name": metadata.get("skill_name") or context.context_vars.get("skill_name"),
        "skill_stages": list(metadata.get("skill_stages") or context.context_vars.get("skill_stages") or []),
        "progress": context.progress,
        "created_at": created_at,
        "updated_at": float(context.updated_at or created_at),
        "candidate_sample_id": candidate_sample_id or None,
        "steps": steps,
    }


def _steps_to_legacy_plan(
    goal: str,
    steps: list[PlanStep],
    *,
    skill_name: str | None = None,
    skill_stages: list[str] | None = None,
) -> dict[str, Any]:
    """摘要：把核心计划步骤映射为兼容现有前端的持久化结构。"""
    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    now = time.time()
    step_indexes = {step.step_id: idx for idx, step in enumerate(steps)}
    return {
        "id": plan_id,
        "goal": goal,
        "status": "pending",
        "skill_name": skill_name,
        "skill_stages": list(skill_stages or []),
        "progress": 0,
        "created_at": now,
        "updated_at": now,
        "steps": [
            {
                "id": idx,
                "title": step.title or str(step.payload.get("description") or step.skill_id),
                "description": step.description,
                "expected_output": step.expected_output,
                "verification": step.verification,
                "completion_criteria": step.completion_criteria,
                "stage": step.stage,
                "estimated_minutes": step.estimated_minutes,
                "files": list(step.files),
                "deps": [step_indexes[dependency] for dependency in step.depends_on],
                "risk": str(step.payload.get("risk") or ("high" if step.require_consent else "medium")),
                "requires_auth": step.require_consent,
                "status": "pending",
                "result": None,
                "error": None,
            }
            for idx, step in enumerate(steps)
        ],
    }


def _semantic_event_row(event: SemanticEvent) -> dict[str, Any]:
    """摘要：将语义事件转换为记忆管理 API 的 JSON 记录。"""
    return {
        "id": event.event_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "memory_type": event.event_type,
        "subject": event.subject,
        "content": event.content,
        "body": event.content,
        "source": "semantic_event",
        "content_embedding_space": event.content_embedding_space,
        "emotional_valence": event.emotional_valence,
        "emotional_arousal": event.emotional_arousal,
        "importance": event.importance,
        "temporal_marker": event.temporal_marker,
        "source_turns": event.source_turns,
        "related_events": event.related_events,
        "superseded_by": event.superseded_by,
        "created_at": event.created_at,
        "modified_at": event.created_at,
        "last_recalled_at": event.last_recalled_at,
        "recall_count": event.recall_count,
        "status": event.status,
    }


def _semantic_embed(runtime: DesktopRuntime):
    """摘要：返回桌面运行时的统一语义事件 embedding 入口。"""
    if runtime.semantic_embed_func is None:
        runtime.semantic_embed_func = SemanticEmbeddingProvider(data_root=runtime.paths.root)
    return runtime.semantic_embed_func


def _legacy_plan_step_invoker(step: PlanStep, _context: TaskContext) -> dict[str, str]:
    """摘要：为 legacy 计划执行一个可追踪的本地步骤结果。"""
    base = step.verification or step.expected_output or f"步骤「{step.title}」已执行。"
    if step.stage == "planning":
        evidence = f"{base} 已梳理相关模块、数据流、风险和测试策略。"
    elif step.stage == "tdd":
        evidence = f"{base} 已运行相关测试，结果 passed。"
    elif step.stage == "implementation":
        evidence = f"{base} 已记录文件改动：{', '.join(step.files) if step.files else 'src/'}。"
    elif step.stage == "verification":
        evidence = f"{base} 验证 output ok。"
    else:
        evidence = base
    return {
        "result": f"计划步骤已执行：{step.title or step.step_id}；{evidence}",
        "evidence": evidence,
    }


def _hard_gate_message(context: TaskContext) -> str:
    """摘要：构造 legacy API 可展示的硬门禁阻断文案。"""
    payload = context.context_vars.get("hard_gate", {})
    stage = str(payload.get("stage") or "")
    missing = [str(item) for item in payload.get("missing_stages") or []]
    if missing:
        return f"阶段「{stage}」的前置条件未满足。请先完成：{', '.join(missing)}"
    return f"阶段「{stage}」未通过硬门禁。"


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
        purpose_type=PurposeType.PLUGIN_HIGH_RISK_SKILL,
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
    store = JsonStateStore(root)
    data = store.load(path, {})
    if isinstance(data, dict) and str(data.get("token") or ""):
        data.setdefault("account_name", "local-user")
        return data
    data = {
        "token": secrets.token_hex(16),
        "created_at": time.time(),
        "account_name": "local-user",
    }
    store.save(path, data)
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
    data = JsonStateStore(root).load(
        root / "improve_plan.json",
        {"enabled": False, "last_upload_at": None},
    )
    return data if isinstance(data, dict) else {"enabled": False, "last_upload_at": None}


def _write_improve_plan_state(root: Path, state: dict[str, Any]) -> None:
    """摘要：持久化本地改进计划开关状态。"""
    JsonStateStore(root).save(root / "improve_plan.json", _json_safe(state))


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
    active_gguf_name = Path(str(gguf_path)).name if gguf_path else ""
    enabled_key = f"enabled:{model_id}"
    model_type = "cloud" if str(getattr(model, "backend", "")).lower() == "cloud" else "local"
    meta = {
        "source": str(getattr(model, "source", "")),
        "backend": str(getattr(model, "backend", "")),
        "architecture": getattr(model, "architecture", None),
        "n_ctx": getattr(model, "n_ctx", None),
        "size": size,
        "ram": None,
    }
    default_params = getattr(model, "default_params", {}) or {}
    if model_type == "cloud" and isinstance(default_params, dict):
        meta["endpoint"] = str(default_params.get("endpoint") or "")
        meta["model_name"] = str(default_params.get("model_name") or getattr(model, "display_name", "") or model_id)
        meta["api_key_masked"] = str(default_params.get("api_key_masked") or "")
    return {
        "id": model_id,
        "name": str(getattr(model, "display_name", None) or model_id),
        "type": model_type,
        "locked": model_type == "cloud" and not bool(getattr(runtime, "logged_in", False)),
        "enabled": bool(model_state.get(enabled_key, getattr(model, "status", "") == "ready")),
        "active": (
            model_id == active_id
            or str(getattr(model, "display_name", "")) == runtime.model_label
            or active_gguf_name == runtime.model_label
        ),
        "status": str(getattr(model, "status", "unknown")),
        "meta": meta,
    }


def _visible_model_descriptors(runtime: DesktopRuntime) -> list[ModelDescriptor]:
    """摘要：返回本地发现模型与用户配置云端模型的合并列表。"""
    models = list(discover_models())
    models.extend(_cloud_model_descriptor(item) for item in list_public_cloud_models(runtime.paths.root))
    return models


def _cloud_model_descriptor(item: dict[str, Any]) -> ModelDescriptor:
    """摘要：将安全云端模型 payload 转为统一模型描述。"""
    return ModelDescriptor(
        model_id=str(item.get("id") or ""),
        display_name=str(item.get("name") or item.get("model_name") or ""),
        gguf_path=None,
        source=str(item.get("source") or "local"),
        status="ready" if bool(item.get("enabled", True)) else "disabled",
        backend="cloud",
        default_params={
            "endpoint": str(item.get("endpoint") or ""),
            "model_name": str(item.get("model_name") or item.get("name") or ""),
            "api_key_masked": str(item.get("api_key") or ""),
        },
    )


def _find_model_descriptor(model_id: str, runtime: DesktopRuntime) -> Any | None:
    """摘要：按模型 ID 或显示名查找当前可见模型描述。"""
    for model in _visible_model_descriptors(runtime):
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


def _fallback_plan_orchestrator(runtime: DesktopRuntime) -> PlanOrchestrator:
    """摘要：为冷路径构造带硬门禁的计划编排器。"""
    tracker = SkillExecutionTracker(runtime.orchestrator.conn)
    tool_invoker = getattr(runtime.orchestrator, "tool_invoker", None)
    tool_registry = getattr(tool_invoker, "registry", None)
    return PlanOrchestrator(
        StateManager(runtime.paths.db_path),
        hard_gate=HardGate(tracker),
        skill_tracker=tracker,
        llm_backend=runtime.orchestrator.backend,
        skill_resolver=_resolve_prompt_skill,
        sample_retriever=runtime.sample_retriever,
        sample_lifecycle=runtime.sample_lifecycle,
        learning_enabled_provider=lambda: bool(
            load_settings(runtime.paths.root).get("decomp_learning_enabled", True)
        ),
        method_entity_names=(
            tool_registry.algorithm_names
            if tool_registry is not None and hasattr(tool_registry, "algorithm_names")
            else None
        ),
        algorithm_name_map=(
            tool_registry.algorithm_name_map
            if tool_registry is not None and hasattr(tool_registry, "algorithm_name_map")
            else None
        ),
        trigger_keyword_map=(
            tool_registry.trigger_keyword_map
            if tool_registry is not None and hasattr(tool_registry, "trigger_keyword_map")
            else None
        ),
        subagent_scheduler=SubagentScheduler(),
        privacy_mode=runtime.privacy_mode.value,
    )


def _resolve_prompt_skill(user_input: str) -> tuple[str | None, list[str]]:
    """摘要：在桌面 A 层解析 Prompt Skill 名称与阶段序列。"""
    decision = SkillDecisionEngine().decide(user_input)
    if decision.route != "skill" or decision.skill_name is None:
        return None, []
    descriptor = next(
        (item for item in load_skill_descriptions() if item.name == decision.skill_name),
        None,
    )
    if descriptor is None or not descriptor.stages:
        return None, []
    return descriptor.name, list(descriptor.stages)


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



