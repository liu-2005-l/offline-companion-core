"""bootstrap：Web/桌面 UI 共用会话与编排器初始化（A1）。"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from offline_companion.core.fallback_controller import FallbackController
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import (
    load_persona_file,
    resolved_companion_display_name,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.plan_orchestrator import PlanOrchestrator
from offline_companion.runtime.inference_backend import (
    EchoBackend,
    create_llama_backend,
    try_stderr_cuda_hint,
)
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.shared.types import AppPaths, PrivacyMode
from offline_companion.shell.policy_engine.rules import default_app_paths
from offline_companion.shell.routed_plan_invoker import CloudRouteInvoker, EchoRouteInvoker, RoutedPlanInvoker
from offline_companion.shell.skill_manager.invoker import SkillInvoker
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.model_registry import (
    resolve_default_gguf_path,
    resolve_default_model_config,
    resolve_n_gpu_layers,
)

ECHO_NO_MODEL_LABEL = "Echo (no model)"


@dataclass
class UISessionBundle:
    paths: AppPaths
    conn: object
    orchestrator: ConversationOrchestrator
    memory_on: bool
    session_id: str
    persona_name: str
    privacy_mode: PrivacyMode
    model_label: str


def resolve_app_paths(data_dir: str | None) -> AppPaths:
    paths = default_app_paths()
    if not data_dir:
        return paths
    root = Path(data_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    paths = AppPaths(root=root, db_path=root / "companion.db", personas_dir=root / "personas", exports_dir=root / "exports")
    paths.personas_dir.mkdir(parents=True, exist_ok=True)
    paths.exports_dir.mkdir(parents=True, exist_ok=True)
    return paths


def bootstrap_ui_session(
    *,
    persona_path: str | Path,
    session_id: str,
    data_dir: str | None = None,
    memory: bool | None = None,
    model: str | None = None,
    n_ctx: int = 2048,
    n_gpu_layers: int = 0,
    privacy: PrivacyMode = PrivacyMode.LOCAL_ONLY,
    session_title: str = "UI",
) -> UISessionBundle:
    paths = resolve_app_paths(data_dir)
    persona = load_persona_file(Path(persona_path).expanduser())
    session_core = PersonaSessionCore(persona)
    memory_on = persona.memory_default_on if memory is None else bool(memory)
    triggers = load_triggers()

    conn = connect(paths.db_path)
    row = conn.execute("SELECT id FROM sessions WHERE id = ?;", (session_id,)).fetchone()
    if not row:
        new_session(conn, session_id, persona.persona_id, title=session_title)

    gguf_path = Path(model).expanduser() if model else resolve_default_gguf_path()
    model_config = None if model else resolve_default_model_config()
    n_gpu = resolve_n_gpu_layers(n_gpu_layers)
    if gguf_path is not None:
        try_stderr_cuda_hint()
        backend = create_llama_backend(
            gguf_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu,
            run_health_check=True,
            model_config=model_config,
        )
        model_label = gguf_path.name
    else:
        backend = EchoBackend("no-model")
        model_label = ECHO_NO_MODEL_LABEL

    orchestrator = ConversationOrchestrator(
        session_core=session_core,
        backend=backend,
        conn=conn,
        session_id=session_id,
        triggers=triggers,
    )

    plan_orchestrator = PlanOrchestrator(conn, paths.personas_dir)
    skill_invoker = SkillInvoker()
    routed_invoker = RoutedPlanInvoker(
        local_invoker=skill_invoker,
        cloud_invoker=CloudRouteInvoker(),
        echo_invoker=EchoRouteInvoker(),
    )
    plan_orchestrator.attach_routed_invoker(routed_invoker)
    plan_orchestrator.attach_fallback_controller(FallbackController())

    return UISessionBundle(
        paths=paths,
        conn=conn,
        orchestrator=orchestrator,
        memory_on=memory_on,
        session_id=session_id,
        persona_name=resolved_companion_display_name(persona),
        privacy_mode=privacy,
        model_label=model_label,
    )


def bootstrap_ui_session_or_exit(args, *, session_title: str = "UI") -> UISessionBundle:
    privacy_raw = getattr(args, "privacy", PrivacyMode.LOCAL_ONLY.value)
    privacy = privacy_raw if isinstance(privacy_raw, PrivacyMode) else PrivacyMode(str(privacy_raw))
    mem_arg = getattr(args, "memory", None)
    memory = None if mem_arg is None else bool(mem_arg)
    try:
        return bootstrap_ui_session(
            persona_path=args.persona,
            session_id=getattr(args, "session_id", None) or str(uuid.uuid4()),
            data_dir=getattr(args, "data_dir", None),
            memory=memory,
            model=getattr(args, "model", None),
            n_ctx=getattr(args, "n_ctx", 2048),
            n_gpu_layers=getattr(args, "n_gpu_layers", 0),
            privacy=privacy,
            session_title=session_title,
        )
    except InferenceBackendError as e:
        print("推理后端初始化失败:", e, file=sys.stderr)
        raise SystemExit(1) from e
