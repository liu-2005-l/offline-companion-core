"""types：跨层数据传输对象（DTO），不含业务执行逻辑。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

# --- 导出包常量（与历史 bundle 兼容） ---
BUNDLE_FORMAT = "offline-companion-bundle"
BUNDLE_VERSION = 1


class PurposeType(str, Enum):
    """摘要：Consent 用途类型（A3；覆盖 Skill / 模组 / 路由 / 沙箱降级）。"""

    SKILL_NETWORK_EGRESS = "skill_network_egress"
    SKILL_FILE_ACCESS = "skill_file_access"
    SKILL_CODE_EXECUTION = "skill_code_execution"
    SKILL_CLOUD_INFERENCE = "skill_cloud_inference"
    CLOUD_ROUTING = "cloud_routing"
    SANDBOX_DOWNGRADE = "sandbox_downgrade"
    NATIVE_RISK_PROMPT = "native_risk_prompt"
    PLUGIN_HIGH_RISK_SKILL = "plugin_high_risk_skill"
    TOOL_EXTERNAL_ENABLE = "tool_external_enable"
    TOOL_USE = "tool_use"
    AGENT_TOOLBOX_HIGH_RISK = "agent_toolbox_high_risk"


class RoutingMode(str, Enum):
    """摘要：路由模式枚举（跨层共享，无 shell 依赖）。"""

    LOCAL = "local"
    CLOUD = "cloud"
    ECHO = "echo"


class PrivacyMode(str, Enum):
    """摘要：出站/云端相关隐私模式。"""

    LOCAL_ONLY = "local_only"
    ASK_BEFORE_CLOUD = "ask_before_cloud"
    ALWAYS_ASK = "always_ask"
    AUTO_ROUTE_CLOUD = "auto_route_cloud"


class OutboundScope(str, Enum):
    """摘要：出站同意范围。"""

    THIS_TURN = "this_turn"
    THIS_SESSION = "this_session"
    GLOBAL = "global"


class CapabilityTag(str, Enum):
    """???????????????????????????? Tool/Skill ???????"""

    CHAT = "chat"
    SIMPLE_QA = "simple_qa"
    COMPLEX_REASONING = "complex_reasoning"
    CODE_GENERATION = "code_generation"
    TOOL_USE = "tool_use"


@dataclass(frozen=True)
class OceanVector:
    """摘要：人格 OCEAN 五维向量，取值范围统一为 0.0-1.0。"""

    openness: float
    conscientiousness: float
    extraversion: float
    agreeableness: float
    neuroticism: float

    def __post_init__(self) -> None:
        for field_name in (
            "openness",
            "conscientiousness",
            "extraversion",
            "agreeableness",
            "neuroticism",
        ):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")



@dataclass(frozen=True)
class AppPaths:
    """摘要：应用本地数据目录解析结果。"""

    root: Path
    db_path: Path
    personas_dir: Path
    exports_dir: Path


@dataclass(frozen=True)
class MessageRow:
    """摘要：单条会话消息行。"""

    role: str
    content: str
    created_at: float
    meta: dict[str, Any]


@dataclass
class MemoryHit:
    """摘要：记忆检索命中项（兼容旧接口）。"""

    id: int
    body: str
    score: float | None


@dataclass
class MemoryRecallHit:
    """摘要：带可解释信息的记忆召回项（B2 `recall` 输出）。"""

    id: int
    body: str
    created_at: float
    combined_score: float
    decay_factor: float
    matched_on: dict[str, Any]


@dataclass(frozen=True)
class ModelRuntimeConfig:
    """???????????? A1 ????? C1 ???"""

    model_id: str
    display_name: str = ""
    backend: str = "llama_cpp"
    architecture: str | None = None
    n_ctx: int | None = None
    supports_system_role: bool = True
    add_bos_token: bool = False
    eos_token: str | None = None
    chat_template: str = ""
    stop_tokens: tuple[str, ...] = ()
    strip_output_tags: tuple[str, ...] = ()
    capability_profile: CapabilityTag = CapabilityTag.CHAT
    default_params: dict[str, Any] = field(default_factory=dict)
    moe: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelDescriptor:
    """???????????????????????"""

    model_id: str
    display_name: str
    gguf_path: str | None
    source: str
    status: str
    backend: str
    architecture: str | None = None
    n_ctx: int | None = None
    supports_system_role: bool = True
    add_bos_token: bool = False
    eos_token: str | None = None
    chat_template: str = ""
    stop_tokens: tuple[str, ...] = ()
    strip_output_tags: tuple[str, ...] = ()
    capability_profile: CapabilityTag = CapabilityTag.CHAT
    default_params: dict[str, Any] = field(default_factory=dict)
    moe: dict[str, Any] | None = None
    incompatible_reason: str | None = None
    missing_fields: tuple[str, ...] = ()




@dataclass(frozen=True)
class TaskProfile:
    """???????????????"""

    task_type: CapabilityTag
    complexity_score: int
    required_capabilities: tuple[CapabilityTag, ...]
    context_length: int
    privacy_sensitive: bool
    requires_network: bool = False


@dataclass(frozen=True)
class ModelRoutingDecision:
    """????????????? A2 ???????"""

    selected_model: str
    fallback_model: str | None
    requires_consent: bool
    reason: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost: float


@dataclass(frozen=True)
class RetrievalHit:
    """摘要：统一检索命中项，供多路融合与展示层复用。"""

    source_type: str
    source_id: str
    title: str | None
    snippet: str
    score: float
    rank: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    """摘要：结构化引用条目，供 UI 与渲染层展示。"""

    index: int
    source_type: str
    source_id: str
    title: str | None
    snippet: str
    score: float


@dataclass(frozen=True)
class HybridSearchResult:
    """摘要：多路检索融合后的统一结果。"""

    hits: tuple[RetrievalHit, ...]
    citations: tuple[Citation, ...]
    display_text: str


@dataclass(frozen=True)
class TurnResult:
    """摘要：``ConversationOrchestrator.run_turn`` 单轮结果（供 A1 渲染）。"""

    reply: str | None = None
    memory_on: bool = True
    blocked_by_safety: bool = False
    safety_tier: str | None = None
    memory_saved: tuple[str, ...] = ()
    memory_skipped_trigger: bool = False
    memory_only: bool = False
    memory_recalls: tuple[MemoryRecallHit, ...] = ()
    memory_explanation: dict[str, Any] | None = None
    cloud_used: bool = False
    cloud_degraded: bool = False
    requires_consent: bool = False
    consent_request_id: str | None = None
    route_mode: str | None = None
    selected_model: str | None = None
    fallback_model: str | None = None
    routing_reason: str | None = None
    estimated_input_tokens: int | None = None
    estimated_output_tokens: int | None = None
    estimated_cost: float | None = None


@dataclass(frozen=True)
class ToolManifest:
    """摘要：Tool 清单元数据，描述 builtin 或 external Tool。"""

    tool_id: str
    display_name: str
    description: str
    tool_type: Literal["builtin", "external"]
    permission: Literal["allow", "ask", "deny"]
    scope: str
    params_schema: dict[str, object]
    return_schema: dict[str, object]
    handler_module: str | None
    handler_function: str | None
    external_config: str | None
    version: str
    audit_only: bool = True
    enabled: bool = True
    endpoint: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """摘要：Tool 执行结果，支持暂停等待 Consent 后恢复。"""

    tool_id: str
    status: Literal["completed", "requires_consent", "denied", "consent_rejected", "error"]
    result: dict[str, object] | None
    error: dict[str, str] | None
    consent_request_id: str | None
    audit_record: dict[str, object]
    duration_ms: float


@dataclass(frozen=True)
class CloudCompletionRequest:
    """摘要：A3 出站推理请求（最小上传）。"""

    user_message: str
    purpose: str


@dataclass(frozen=True)
class CloudCompletionResponse:
    """摘要：A3 出站推理响应。"""

    text: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class Persona:
    """摘要：已加载人设；`role_lock` 为真时仅使用本系统提示。

    说明：
        `name` 为人设模板/catalog 显示名，非模型对用户的自称。
        陪伴自称由 ``companion_display_name``（宿主注册）或
        ``default_companion_display_name``（如「助手一号」）决定。
    """

    persona_id: str
    name: str
    system_prompt: str
    role_lock: bool
    memory_default_on: bool
    default_companion_display_name: str
    companion_display_name: str | None
    raw: dict[str, Any]
    ocean: OceanVector | None = None


@dataclass(frozen=True)
class OutboundPlan:
    """摘要：出站前向用户披露的计划（最小上传说明）。"""

    payload_excerpt: str
    will_send: list[str]
    will_not_send: list[str]
    purpose: str
    scope: OutboundScope


@dataclass(frozen=True)
class ExportBundlePayload:
    """摘要：已由 B2 组装完成的导出包载荷；C2 仅序列化与落盘，不解释业务字段。

    参数：
        manifest: manifest.json 对应字典。
        persona_json: persona.json 文本。
        sessions_jsonl: sessions 表 JSONL。
        messages_jsonl: messages 表 JSONL。
        memory_chunks_jsonl: memory_chunks 表 JSONL。
    """

    manifest: dict[str, Any]
    persona_json: str
    sessions_jsonl: str
    messages_jsonl: str
    memory_chunks_jsonl: str
