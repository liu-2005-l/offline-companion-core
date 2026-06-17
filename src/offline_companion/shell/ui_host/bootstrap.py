"""bootstrap：Web/桌面 UI 共用会话与编排器初始化（A1）。"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import (
    load_persona_file,
    resolved_companion_display_name,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.inference_backend import (
    EchoBackend,
    create_llama_backend,
    try_stderr_cuda_hint,
)
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.shared.types import AppPaths, PrivacyMode
from offline_companion.shell.policy_engine.rules import default_app_paths
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.model_registry import (
    resolve_default_gguf_path,
    resolve_n_gpu_layers,
)

# 未配置 GGUF 时底栏展示文案（区分「故意 Echo」与「模型路径未填」）
ECHO_NO_MODEL_LABEL = "Echo (no model)"


@dataclass
class UISessionBundle:
    """摘要：UI 宿主启动后持有的会话与编排上下文。"""

    paths: AppPaths
    conn: object
    orchestrator: ConversationOrchestrator
    memory_on: bool
    session_id: str
    persona_name: str
    # 仅供 A1 底栏/设置展示；出站与路由决策由 A2 policy_engine 负责，不注入编排器
    privacy_mode: PrivacyMode
    model_label: str


def resolve_app_paths(data_dir: str | None) -> AppPaths:
    """摘要：解析数据目录（``--data-dir`` 或系统默认）。

    参数：
        data_dir: 可选覆盖路径。

    返回值：
        ``AppPaths`` 实例（必要子目录已创建）。
    """
    paths = default_app_paths()
    if not data_dir:
        return paths
    root = Path(data_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    paths = AppPaths(
        root=root,
        db_path=root / "companion.db",
        personas_dir=root / "personas",
        exports_dir=root / "exports",
    )
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
    """摘要：加载人设、推理后端与会话，构造 ``ConversationOrchestrator``。

    参数：
        persona_path: persona YAML 路径。
        session_id: SQLite 会话 ID。
        data_dir: 可选数据根覆盖。
        memory: 记忆开关；``None`` 时用人设默认。
        model: GGUF 路径；省略则读 ``models/registry.yaml`` 等（见 ``model_registry``）。
        n_ctx: 上下文长度（GGUF）。
        n_gpu_layers: GPU 层数（GGUF）。
        privacy: 隐私模式（桌面底栏展示；出站逻辑由后续 Consent 接入）。
        session_title: 新建会话时的标题。

    返回值：
        ``UISessionBundle``。

    Raises:
        InferenceBackendError: GGUF 后端初始化失败。
    """
    paths = resolve_app_paths(data_dir)
    persona = load_persona_file(Path(persona_path).expanduser())
    session_core = PersonaSessionCore(persona)
    memory_on = persona.memory_default_on if memory is None else bool(memory)
    triggers = load_triggers()

    conn = connect(paths.db_path)
    row = conn.execute("SELECT id FROM sessions WHERE id = ?;", (session_id,)).fetchone()
    if not row:
        # 桌面壳单实例下无并发写会话问题；多宿主并发时再考虑 WAL 或显式锁
        new_session(conn, session_id, persona.persona_id, title=session_title)

    gguf_path = Path(model).expanduser() if model else resolve_default_gguf_path()
    n_gpu = resolve_n_gpu_layers(n_gpu_layers)

    if gguf_path is not None:
        try_stderr_cuda_hint()
        backend = create_llama_backend(
            gguf_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu,
            run_health_check=True,
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
    """摘要：从 argparse 命名空间引导 UI 会话；失败时打印并 ``sys.exit(1)``。"""
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
