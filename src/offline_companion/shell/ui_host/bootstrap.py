"""bootstrap：Web/桌面 UI 共用会话与编排器初始化（A1）。"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from offline_companion.core.attention_awareness import AttentionContext, AttentionGuard
from offline_companion.core.decomposition_sample_library import (
    SampleLifecycleManager,
    SampleMaintenance,
    SampleRepository,
    SampleRetriever,
)
from offline_companion.core.event_stream import (
    EventPersistence,
    StreamManager,
    build_default_registry,
)
from offline_companion.core.fallback_controller import FallbackController
from offline_companion.core.goal_manager import GoalEvaluator, GoalManager, GoalRepository
from offline_companion.core.hard_gate import HardGate
from offline_companion.core.memory_lifecycle.event_extractor import EventExtractor
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.idle_hook import MemoryIdleHook
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import (
    load_persona_file,
    resolved_companion_display_name,
)
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.plan_orchestrator import (
    A3ConsentAdapter,
    EventStreamPlanEventPublisher,
    PlanOrchestrator,
    PlanStatus,
    StateManagerPlanEventPublisher,
)
from offline_companion.core.skill_execution_tracker import SkillExecutionTracker
from offline_companion.core.state_manager import StateManager
from offline_companion.core.subagent_scheduler import RestrictedToolRegistry, SubagentScheduler
from offline_companion.core.subagent_types import SubagentContext, SubagentRouterResponse
from offline_companion.core.tools.booth_tool import booth_multiply_tool
from offline_companion.core.tools.calculator_tool import calculator_tool
from offline_companion.core.tools.crc32_tool import crc32_tool
from offline_companion.core.tools.gcd_tool import gcd_tool
from offline_companion.core.tools.quicksort_tool import quicksort_tool
from offline_companion.runtime.inference_backend import (
    EchoBackend,
    LlamaServerStartupError,
    create_llama_backend,
    try_stderr_cuda_hint,
)
from offline_companion.runtime.storage_index.engine import connect, new_session, recent_messages
from offline_companion.shared.deterministic_embedding import embed_text
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.shared.types import AppPaths, MessageRow, PrivacyMode, ToolManifest
from offline_companion.shell.auto_router import AutoRouter, RoutingContext
from offline_companion.shell.auto_turn_orchestrator import (
    AutoTurnOrchestrator,
    ConversationPlanInvoker,
)
from offline_companion.shell.idle_think_coordinator import IdleThinkCoordinator
from offline_companion.shell.model_router import ModelRouter
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.outbound_manager.connector import post_cloud_completion
from offline_companion.shell.plan_auto_bridge import PlanAutoBridge
from offline_companion.shell.policy_engine.rules import default_app_paths
from offline_companion.shell.routed_plan_invoker import (
    CloudRouteInvoker,
    EchoRouteInvoker,
    RoutedPlanInvoker,
)
from offline_companion.shell.skill_router import SkillDecisionEngine, load_skill_descriptions
from offline_companion.shell.tool_registry import (
    ToolInvoker,
    ToolRegistry,
    register_skill_advance_stage_tool,
)
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.shell.ui_host.desktop.idle_detector import IdleDetector
from offline_companion.shell.ui_host.model_downloader import ModelDownloader
from offline_companion.shell.ui_host.model_registry import (
    BUILTIN_MODELS,
    resolve_active_model_id,
    resolve_default_gguf_path,
    resolve_default_model_config,
    resolve_n_gpu_layers,
)
from offline_companion.storage.cloud_model_repo import list_cloud_models
from offline_companion.storage.json_state_store import check_state_integrity
from offline_companion.storage.settings_store import load_settings

ECHO_NO_MODEL_LABEL = "Echo (no model)"


class _SubagentRouterAdapter:
    """摘要：将本地推理后端适配为 SubagentScheduler 期望的 route() 接口。"""

    def __init__(self, backend: object, *, max_tokens: int = 512) -> None:
        """摘要：初始化子 Agent 本地生成适配器。

        参数：
            backend: 支持 ``generate`` 的本地推理后端。
            max_tokens: 单次子 Agent 回复的最大 token 数。
        """
        self._backend = backend
        self._max_tokens = max_tokens

    def route(
        self,
        *,
        messages: list[dict[str, Any]],
        system_prompt: str,
        privacy_mode: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> SubagentRouterResponse:
        """摘要：调用本地后端生成文本；当前生产适配不声明工具调用能力。"""
        del privacy_mode
        prompt = self._build_user_message(messages, tools)
        generate = getattr(self._backend, "generate", None)
        if generate is None:
            return SubagentRouterResponse(content="", tool_calls=[], finish_reason="error")
        content = generate(
            system_prompt=system_prompt,
            history=self._history_from_messages(messages),
            user_message=prompt,
            memory_block="",
            max_tokens=self._max_tokens,
        )
        return SubagentRouterResponse(content=str(content), tool_calls=[], finish_reason="stop")

    @staticmethod
    def _build_user_message(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> str:
        """摘要：从隔离消息链中提取当前用户任务，并附加可用工具说明。"""
        user_message = next(
            (str(item.get("content") or "") for item in reversed(messages) if item.get("role") == "user"),
            "",
        )
        if not tools:
            return user_message
        tool_names = [
            str((tool.get("function") or {}).get("name") or "")
            for tool in tools
            if isinstance(tool, dict)
        ]
        tool_block = ", ".join(name for name in tool_names if name) or "none"
        return f"{user_message}\n\n可用工具：{tool_block}\n如需工具调用，请按当前子 Agent 协议返回结构化请求。"

    @staticmethod
    def _history_from_messages(messages: list[dict[str, Any]]) -> list[MessageRow]:
        """摘要：将子 Agent 消息链转换为本地后端 history，排除 system 与最后一条 user。"""
        history: list[MessageRow] = []
        for item in messages[1:-1]:
            role = str(item.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            history.append(MessageRow(role=role, content=str(item.get("content") or ""), created_at=0.0, meta={}))
        return history


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
    backend_mode: str
    local_available: bool
    cloud_available: bool
    local_error: str | None
    active_cloud_model_id: str | None
    repaired_state_files: tuple[str, ...]
    plan_orchestrator: PlanOrchestrator
    auto_turn_orchestrator: AutoTurnOrchestrator
    idle_detector: IdleDetector
    idle_coordinator: IdleThinkCoordinator
    state_manager: StateManager
    sample_repository: SampleRepository
    sample_lifecycle: SampleLifecycleManager
    sample_retriever: SampleRetriever
    event_stream_manager: StreamManager | None = None
    event_persistence: EventPersistence | None = None


def _configured_cloud_model(paths: AppPaths, settings: dict[str, Any]) -> dict[str, Any] | None:
    """摘要：选择本地保存或环境变量提供的完整云端模型配置。"""
    models = list_cloud_models(paths.root)
    active_model_id = str(settings.get("active_model_id") or "").strip()
    candidates = sorted(
        models,
        key=lambda item: str(item.get("id") or "") != active_model_id,
    )
    for item in candidates:
        if not bool(item.get("enabled", True)):
            continue
        if all(str(item.get(key) or "").strip() for key in ("endpoint", "model_name", "api_key")):
            return item
    endpoint = os.environ.get("OFFLINE_COMPANION_CLOUD_URL", "").strip()
    model_name = os.environ.get("OFFLINE_COMPANION_CLOUD_MODEL", "").strip()
    api_key = os.environ.get("OFFLINE_COMPANION_CLOUD_API_KEY", "").strip()
    if endpoint and model_name and api_key:
        return {
            "id": "environment",
            "name": model_name,
            "endpoint": endpoint,
            "model_name": model_name,
            "api_key": api_key,
            "enabled": True,
        }
    return None


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


def _resolve_prompt_skill(user_input: str) -> tuple[str | None, list[str]]:
    """摘要：在 A 层解析 Prompt Skill 名称与阶段序列。"""
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


def _make_subagent_tool_registry_factory(
    base_tool_invoker: object,
    consent_gateway: object | None,
):
    """摘要：构造子 Agent 受限工具注册表工厂。"""

    def factory(ctx: SubagentContext) -> RestrictedToolRegistry:
        """摘要：按子 Agent 上下文创建受限工具注册表。"""
        return RestrictedToolRegistry(
            base=base_tool_invoker,
            allowed_files=ctx.allowed_files,
            role=ctx.role,
            consent_gateway=consent_gateway,
        )

    return factory


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
    repaired_state_files = tuple(check_state_integrity(paths.root))
    settings_state = load_settings(paths.root)
    persona = load_persona_file(Path(persona_path).expanduser())
    session_core = PersonaSessionCore(persona)
    memory_on = persona.memory_default_on if memory is None else bool(memory)
    triggers = load_triggers()

    conn = connect(paths.db_path)
    event_persistence = EventPersistence(paths.db_path)
    event_stream_manager = StreamManager(build_default_registry(), event_persistence)
    event_stream_manager.restore_from_disk()
    event_stream = event_stream_manager.get_or_create(session_id)
    sample_repository = SampleRepository(conn)
    sample_lifecycle = SampleLifecycleManager(sample_repository, event_stream)
    sample_retriever = SampleRetriever(conn, sample_repository, event_stream)
    row = conn.execute("SELECT id FROM sessions WHERE id = ?;", (session_id,)).fetchone()
    if not row:
        new_session(conn, session_id, persona.persona_id, title=session_title)

    gguf_path = Path(model).expanduser() if model else resolve_default_gguf_path()
    model_config = None if model else resolve_default_model_config()
    n_gpu = resolve_n_gpu_layers(n_gpu_layers)
    local_available = False
    local_error: str | None = None
    if gguf_path is not None:
        active_local_model_id = resolve_active_model_id() if model is None else None
        verification_entry = next(
            (entry for entry in BUILTIN_MODELS if entry.model_id == active_local_model_id),
            None,
        )
        integrity_ok = True
        if verification_entry is not None:
            integrity_ok = ModelDownloader(
                BUILTIN_MODELS,
                event_stream=event_stream,
            ).verify_local_model(verification_entry.model_id, gguf_path)
        try:
            if not integrity_ok:
                raise InferenceBackendError("模型文件校验失败，请重新下载")
            try_stderr_cuda_hint()
            backend = create_llama_backend(
                gguf_path,
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu,
                run_health_check=True,
                model_config=model_config,
            )
            local_available = True
        except (LlamaServerStartupError, InferenceBackendError, OSError) as exc:
            backend = EchoBackend("local-unavailable")
            local_error = str(exc)
        model_label = gguf_path.name
    else:
        backend = EchoBackend("local-unavailable")
        model_label = ECHO_NO_MODEL_LABEL
        local_error = "未配置本地模型"

    cloud_model = _configured_cloud_model(paths, settings_state)
    cloud_available = cloud_model is not None
    if local_available:
        backend_mode = "local"
    elif cloud_available and privacy is not PrivacyMode.LOCAL_ONLY:
        backend_mode = "cloud_fallback"
    else:
        backend_mode = "no_backend"

    consent_gateway = UIHostConsentGateway(db_conn=conn, event_stream=event_stream)
    tool_registry = ToolRegistry()
    register_skill_advance_stage_tool(tool_registry, conn)
    tool_registry.register_builtin(
        ToolManifest(
            tool_id="algorithm_booth",
            display_name="Booth 算法",
            description="本地确定性整数乘法，返回重编码、部分积和寄存器中间态。",
            tool_type="builtin",
            permission="allow",
            scope="local_computation",
            params_schema={
                "type": "object",
                "required": ["multiplicand", "multiplier"],
                "properties": {
                    "multiplicand": {"type": "integer"},
                    "multiplier": {"type": "integer"},
                },
            },
            return_schema={"type": "object"},
            handler_module="offline_companion.core.tools.booth_tool",
            handler_function="booth_multiply_tool",
            external_config=None,
            version="1.0.0",
            algorithm_names=("booth",),
            trigger_keywords=("booth",),
        ),
        booth_multiply_tool,
    )
    tool_registry.register_builtin(
        ToolManifest(
            tool_id="calculator",
            display_name="calculator",
            description="本地确定性基础算术工具，支持四则与整数幂。",
            tool_type="builtin",
            permission="allow",
            scope="local_computation",
            params_schema={
                "type": "object",
                "required": ["left", "operator", "right"],
                "properties": {
                    "left": {"type": ["string", "integer"]},
                    "operator": {"type": "string"},
                    "right": {"type": ["string", "integer"]},
                },
            },
            return_schema={"type": "object"},
            handler_module="offline_companion.core.tools.calculator_tool",
            handler_function="calculator_tool",
            external_config=None,
            version="1.0.0",
        ),
        calculator_tool,
    )
    tool_registry.register_builtin(
        ToolManifest(
            tool_id="algorithm_crc32",
            display_name="CRC-32 算法",
            description="本地确定性 CRC-32 UTF-8 校验，返回按位迭代轨迹与校验值。",
            tool_type="builtin",
            permission="allow",
            scope="local_computation",
            params_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            return_schema={"type": "object"},
            handler_module="offline_companion.core.tools.crc32_tool",
            handler_function="crc32_tool",
            external_config=None,
            version="1.0.0",
            algorithm_names=("crc", "crc32", "crc-32"),
            trigger_keywords=("crc", "crc32", "crc-32"),
        ),
        crc32_tool,
    )
    tool_registry.register_builtin(
        ToolManifest(
            tool_id="algorithm_gcd",
            display_name="欧几里得算法",
            description="本地确定性最大公约数工具，返回辗转相除余数序列。",
            tool_type="builtin",
            permission="allow",
            scope="local_computation",
            params_schema={
                "type": "object",
                "required": ["left", "right"],
                "properties": {
                    "left": {"type": "integer"},
                    "right": {"type": "integer"},
                },
            },
            return_schema={"type": "object"},
            handler_module="offline_companion.core.tools.gcd_tool",
            handler_function="gcd_tool",
            external_config=None,
            version="1.0.0",
            algorithm_names=("欧几里得", "gcd"),
            trigger_keywords=("最大公约数", "gcd"),
        ),
        gcd_tool,
    )
    tool_registry.register_builtin(
        ToolManifest(
            tool_id="algorithm_quicksort",
            display_name="快速排序算法",
            description="本地确定性快速排序工具，返回每轮分区快照。",
            tool_type="builtin",
            permission="allow",
            scope="local_computation",
            params_schema={
                "type": "object",
                "required": ["values"],
                "properties": {"values": {"type": "array", "items": {"type": "integer"}}},
            },
            return_schema={"type": "object"},
            handler_module="offline_companion.core.tools.quicksort_tool",
            handler_function="quicksort_tool",
            external_config=None,
            version="1.0.0",
            algorithm_names=("快速排序", "quicksort"),
            trigger_keywords=("快速排序", "quicksort"),
        ),
        quicksort_tool,
    )
    tool_invoker = ToolInvoker(tool_registry, consent_gateway=consent_gateway, event_stream=event_stream)
    orchestrator = ConversationOrchestrator(
        session_core=session_core,
        backend=backend,
        conn=conn,
        session_id=session_id,
        triggers=triggers,
        privacy_mode=privacy,
        model_router=ModelRouter(),
        consent_gateway=consent_gateway,
        cloud_post=post_cloud_completion,
        cloud_model_provider=lambda: cloud_model,
        backend_mode=backend_mode,
        local_available=local_available,
        cloud_available=cloud_available,
        tool_invoker=tool_invoker,
        event_stream=event_stream,
        event_extractor=(
            EventExtractor(
                EventRepository(conn),
                backend,
                lambda text: embed_text(text, dimensions=768),
            )
            if local_available
            else None
        ),
    )

    state_manager = StateManager(paths.db_path)
    skill_tracker = SkillExecutionTracker(conn)
    plan_orchestrator = PlanOrchestrator(
        state_manager,
        paths.personas_dir,
        consent_adapter=A3ConsentAdapter(consent_gateway),
        consent_gateway=consent_gateway,
        llm_backend=backend,
        hard_gate=HardGate(skill_tracker),
        skill_tracker=skill_tracker,
        skill_resolver=_resolve_prompt_skill,
        sample_retriever=sample_retriever,
        sample_lifecycle=sample_lifecycle,
        learning_enabled_provider=lambda: bool(
            load_settings(paths.root).get("decomp_learning_enabled", True)
        ),
        method_entity_names=tool_registry.algorithm_names,
        algorithm_name_map=tool_registry.algorithm_name_map,
        trigger_keyword_map=tool_registry.trigger_keyword_map,
        subagent_scheduler=SubagentScheduler(
            auto_router=_SubagentRouterAdapter(backend),
            consent_gateway=consent_gateway,
            tool_registry_factory=_make_subagent_tool_registry_factory(
                base_tool_invoker=tool_invoker,
                consent_gateway=consent_gateway,
            ),
        ),
        privacy_mode=privacy.value,
        event_publisher=EventStreamPlanEventPublisher(
            StateManagerPlanEventPublisher(state_manager), event_stream
        ),
    )
    conversation_plan_invoker = ConversationPlanInvoker(orchestrator)
    routed_invoker = RoutedPlanInvoker(
        local_invoker=conversation_plan_invoker,
        cloud_invoker=CloudRouteInvoker(
            cloud_model_provider=lambda: (
                orchestrator.cloud_model_provider() if orchestrator.cloud_model_provider else None
            )
        ),
        echo_invoker=EchoRouteInvoker(),
    )
    plan_orchestrator.attach_routed_invoker(routed_invoker)
    plan_orchestrator.attach_fallback_controller(FallbackController())
    auto_bridge = PlanAutoBridge(
        auto_router=AutoRouter(),
        plan_orchestrator=plan_orchestrator,
        context_factory=lambda message: RoutingContext(
            query=str(message.payload.get("user_input") or message.topic),
            privacy_mode=orchestrator.privacy_mode.value,
        ),
    )
    auto_turn_orchestrator = AutoTurnOrchestrator(
        plan_orchestrator=plan_orchestrator,
        auto_bridge=auto_bridge,
        invoke_skill=routed_invoker.invoke_step,
        event_stream=event_stream,
        final_reply_summarizer=conversation_plan_invoker.summarize_final_reply,
    )
    goal_repository = GoalRepository(conn)
    goal_manager = GoalManager(
        repository=goal_repository,
        evaluator=GoalEvaluator(goal_repository),
        guard=AttentionGuard(),
    )
    memory_idle_hook = None
    if orchestrator.event_extractor is not None:
        class _SessionWindow:
            def get_pending_extraction(self):
                current_row = conn.execute(
                    "SELECT COUNT(*) AS count FROM messages WHERE session_id = ? AND role = 'user'",
                    (session_id,),
                ).fetchone()
                current_turn = int(current_row["count"]) if current_row is not None else 0
                last_turn = orchestrator.event_extractor.last_extracted_turn
                if current_turn <= last_turn:
                    return None
                messages = recent_messages(conn, session_id, limit=20)
                return (
                    session_id,
                    [{"role": item.role, "content": item.content} for item in messages],
                    (max(1, last_turn + 1), current_turn),
                )

        memory_idle_hook = MemoryIdleHook(
            orchestrator.event_extractor,
            EventRepository(conn),
            _SessionWindow(),
        )
    sample_maintenance = SampleMaintenance(
        sample_repository,
        sample_lifecycle,
        plan_failed_provider=lambda plan_id: (
            (context := plan_orchestrator.load_context(plan_id)) is not None
            and (context.status is PlanStatus.FAILED or context.plan_status == "failed")
        ),
    )
    idle_coordinator = IdleThinkCoordinator(
        goal_manager=goal_manager,
        state_manager=state_manager,
        attention_context_provider=lambda: AttentionContext(is_idle=True),
        settings_provider=lambda: load_settings(paths.root),
        plan_orchestrator=plan_orchestrator,
        memory_maintenance=memory_idle_hook.on_idle if memory_idle_hook is not None else None,
        sample_maintenance=sample_maintenance.run,
    )
    idle_detector = IdleDetector(
        threshold_seconds=float(settings_state.get("idle_threshold_seconds", 300)),
        check_interval_seconds=30,
        on_idle=idle_coordinator.on_idle,
        on_user_input=idle_coordinator.on_user_input,
    )
    if bool(settings_state.get("idle_think_enabled", True)):
        idle_detector.start()

    return UISessionBundle(
        paths=paths,
        conn=conn,
        orchestrator=orchestrator,
        memory_on=memory_on,
        session_id=session_id,
        persona_name=resolved_companion_display_name(persona),
        privacy_mode=privacy,
        model_label=model_label,
        backend_mode=backend_mode,
        local_available=local_available,
        cloud_available=cloud_available,
        local_error=local_error,
        active_cloud_model_id=(str(cloud_model.get("id")) if cloud_model else None),
        repaired_state_files=repaired_state_files,
        plan_orchestrator=plan_orchestrator,
        auto_turn_orchestrator=auto_turn_orchestrator,
        idle_detector=idle_detector,
        idle_coordinator=idle_coordinator,
        state_manager=state_manager,
        sample_repository=sample_repository,
        sample_lifecycle=sample_lifecycle,
        sample_retriever=sample_retriever,
        event_stream_manager=event_stream_manager,
        event_persistence=event_persistence,
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
