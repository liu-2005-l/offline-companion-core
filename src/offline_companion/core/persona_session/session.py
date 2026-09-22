"""session：人格锁与会话装配（B1）。"""

from __future__ import annotations

import logging
import os
import sqlite3
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

import yaml

from offline_companion.core.arithmetic_verifier import ArithmeticAuditResult, audit_arithmetic_reply
from offline_companion.core.emotion_analyzer.context import EmotionContext
from offline_companion.core.memory_lifecycle.event_recaller import (
    EventRecaller,
    format_event_narrative,
)
from offline_companion.core.memory_lifecycle.event_repository import EventRepository
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.recall import format_recall_prompt_block, recall
from offline_companion.core.memory_lifecycle.semantic_embedding_provider import (
    SemanticEmbeddingProvider,
)
from offline_companion.core.persona_constraint import (
    AUDIT_ARITHMETIC_WARNING_APPENDED,
    L3_INVALID_EMOTION_SIGNAL,
    L3_STANDARD_INTENSITY,
    L4_DIRECT,
    L4_FALLBACK,
    L4_OBSERVE,
    L4_RETRY,
    PersonaConstraintAssets,
    PersonaL1AssemblyError,
    PersonaL3Decision,
    PersonaL3Policy,
    PersonaL3Trace,
    PersonaL4Decision,
    PersonaL4Outcome,
    PersonaL4Policy,
    PersonaL4Trace,
    PersonaTurnSignals,
    assemble_l1_prompt,
    build_l4_retry_instruction,
    deterministic_l4_fallback,
    finalize_l1_prompt,
    l3_frozen_l1_mapping,
    l4_policy_from_assets,
    policy_from_assets,
    resolve_l3,
    resolve_l4,
)
from offline_companion.core.persona_session.expression import (
    STYLE_BLOCK_HEADER,
    PersonaExpressionConfig,
    PersonaExpressionTrace,
    append_ephemeral_identity_reminder,
    build_identity_reminder,
    build_identity_retry_reminder,
    build_style_examples_block,
    detect_identity_cliff,
    deterministic_identity_fallback,
    is_identity_intent,
    warn_identity_fallback_once,
)
from offline_companion.core.persona_session.persona_loader import resolved_companion_display_name
from offline_companion.shared.runtime_paths import configs_dir, dev_repo_root
from offline_companion.shared.types import (
    CapabilityProfile,
    MemoryRecallHit,
    MessageRow,
    OceanVector,
    Persona,
)

_EMOTION_STRATEGIES: dict[str, dict[str, str]] | None = None
_OCEAN_TONE_MAPPINGS: dict[str, dict[str, object]] | None = None
_ASSISTANT_NAME_QUESTION_KEYWORDS = ("你叫什么", "你的名字", "你叫啥", "你是谁")
_DISPLAY_NAME_MAX_CHARS = 32
SKILL_BOOTSTRAP_PROMPT = """\
## 技能感知

在处理复杂任务前，检查是否有匹配的技能定义（SKILL.md）。
如果用户请求匹配某 skill 的 description，必须优先按该 skill 的 Iron Laws 和 Procedure 执行。

技能定义位于 skills/ 目录下。每个 skill 的 SKILL.md 声明了：
- When to Use（适用场景）
- Iron Laws（不可绕过的硬规则）
- Procedure（具体执行步骤）
"""

logger = logging.getLogger(__name__)


def _trace_from_decision(
    decision: PersonaL3Decision,
    *,
    prompt_replaced: bool = False,
    structural_sample_id: str | None = None,
    closure_reason: str | None = None,
) -> PersonaL3Trace:
    """摘要：把纯谓词结果投影为逐轮应用 trace。"""
    return PersonaL3Trace(
        result=decision.result,
        trace_code=decision.trace_code,
        constraints_enabled=decision.constraints_enabled and closure_reason is None,
        prompt_replaced=prompt_replaced,
        structural_sample_id=structural_sample_id,
        audit_event=decision.audit_event,
        closure_reason=closure_reason,
    )


def _l4_observe_warning(decision: PersonaL4Decision) -> str:
    """摘要：把 observe-only 命中压成稳定 warning 码。"""
    return f"l4_observe:{decision.zone or 'unknown'}:{decision.family or 'unknown'}"


def _l4_trace(
    first: PersonaL4Decision,
    *,
    outcome: PersonaL4Outcome,
    retry: PersonaL4Decision | None = None,
    retry_taken: bool = False,
    warnings: tuple[str, ...] = (),
) -> PersonaL4Trace:
    """摘要：把两次以内的纯扫描判定投影为稳定运行时 trace。"""
    return PersonaL4Trace(
        enabled=True,
        outcome=outcome,
        first_zone=first.zone,
        first_family=first.family,
        retry_zone=retry.zone if retry is not None else None,
        retry_family=retry.family if retry is not None else None,
        retry_taken=retry_taken,
        warnings=warnings,
    )


def _buffered_replay_chunks(text: str, *, chunk_size: int = 32) -> Iterator[str]:
    """摘要：把已通过审计的最终正文按稳定字符窗口回放为 SSE token。"""
    body = str(text or "")
    for offset in range(0, len(body), chunk_size):
        yield body[offset : offset + chunk_size]


def _load_yaml_dict(file_name: str) -> dict[str, object]:
    """摘要：按运行时配置优先级加载 YAML 字典。"""
    candidates = [
        configs_dir() / file_name,
        dev_repo_root() / "configs" / file_name,
    ]
    for path in candidates:
        if not path.is_file():
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return raw if isinstance(raw, dict) else {}
    return {}


def _load_emotion_strategies() -> dict[str, dict[str, str]]:
    """摘要：从 ``configs/emotion_mappings.yaml`` 加载情绪策略。"""
    global _EMOTION_STRATEGIES
    if _EMOTION_STRATEGIES is not None:
        return _EMOTION_STRATEGIES
    raw = _load_yaml_dict("emotion_mappings.yaml")
    strategies = raw.get("emotion_strategies", {})
    _EMOTION_STRATEGIES = {k: v for k, v in strategies.items() if isinstance(v, dict)}
    return _EMOTION_STRATEGIES


def _load_ocean_tone_mappings() -> dict[str, dict[str, object]]:
    """摘要：从 ``configs/ocean_tone_mappings.yaml`` 加载 OCEAN 语气映射。"""
    global _OCEAN_TONE_MAPPINGS
    if _OCEAN_TONE_MAPPINGS is not None:
        return _OCEAN_TONE_MAPPINGS
    raw = _load_yaml_dict("ocean_tone_mappings.yaml")
    dimensions = raw.get("dimensions", {})
    _OCEAN_TONE_MAPPINGS = {k: v for k, v in dimensions.items() if isinstance(v, dict)}
    return _OCEAN_TONE_MAPPINGS


def _build_emotion_instruction(emotion_context: EmotionContext | None) -> str:
    """摘要：根据情绪上下文生成系统指令片段。"""
    if emotion_context is None or emotion_context.emotion == "neutral":
        return ""
    strategies = _load_emotion_strategies()
    entry = strategies.get(emotion_context.emotion)
    if entry is None:
        return ""
    instruction = str(entry.get("system_instruction") or "").strip()
    if not instruction:
        return ""
    return f"\n【情绪策略】{instruction}\n"


def _build_tone_instruction(ocean: OceanVector | None) -> str:
    """摘要：根据 OCEAN 向量生成语气风格指令，只描述显著维度。"""
    if ocean is None:
        return ""
    mappings = _load_ocean_tone_mappings()
    descriptors: list[str] = []
    values = {
        "openness": ocean.openness,
        "conscientiousness": ocean.conscientiousness,
        "extraversion": ocean.extraversion,
        "agreeableness": ocean.agreeableness,
        "neuroticism": ocean.neuroticism,
    }
    for dim_name, value in values.items():
        entry = mappings.get(dim_name)
        if entry is None:
            continue
        band = _resolve_ocean_band(entry, value)
        if band == "high":
            descriptors.extend(_descriptor_list(entry.get("descriptors")))
        elif band == "low":
            descriptors.extend(_descriptor_list(entry.get("low_descriptors")))
    if not descriptors:
        return ""
    unique_descriptors = list(dict.fromkeys(descriptors))
    return f"\n【语气风格】语气风格：{', '.join(unique_descriptors)}。\n"


def _resolve_ocean_band(entry: dict[str, object], value: float) -> str | None:
    """摘要：按阈值判断当前维度属于高段、低段或中间段。"""
    high = entry.get("high")
    low = entry.get("low")
    if isinstance(high, (list, tuple)) and len(high) == 2 and float(high[0]) <= value <= float(high[1]):
        return "high"
    if isinstance(low, (list, tuple)) and len(low) == 2 and float(low[0]) <= value <= float(low[1]):
        return "low"
    return None


def _descriptor_list(value: object) -> list[str]:
    """摘要：将配置中的描述列表标准化为字符串列表。"""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _sanitize_display_name(value: object) -> str:
    """摘要：将画像记忆中的自称规范化为安全的单行短文本，避免注入系统提示。"""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    safe_chars: list[str] = []
    for char in text:
        if char in {" ", "-", "_", "·", "・"}:
            safe_chars.append(char)
            continue
        category = unicodedata.category(char)
        if category[0] in {"L", "N"}:
            safe_chars.append(char)
    return "".join(safe_chars).strip()[:_DISPLAY_NAME_MAX_CHARS]


def effective_companion_display_name(
    persona: Persona,
    conn: sqlite3.Connection | None = None,
) -> str:
    """摘要：按画像记忆优先级解析并净化当前有效自称。

    参数：
        persona: 当前会话人格定义。
        conn: 可选记忆数据库连接；提供时优先读取助手画像自称。

    返回值：
        最长 32 个 Unicode 字符的安全单行自称。
    """
    if conn is not None:
        profile = MemoryLifecycleManager.latest_profile_memory(conn)
        display_name = _sanitize_display_name(profile.get("assistant", {}).get("display_name"))
        if display_name:
            return display_name
    return _sanitize_display_name(resolved_companion_display_name(persona))


@runtime_checkable
class InferenceBackend(Protocol):
    """摘要：B1 所依赖的 C1 推理后端最小协议。"""

    def generate(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> str: ...

    def generate_stream(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> Iterator[str]: ...


@dataclass(frozen=True)
class AssembleReplyResult:
    """摘要：单轮装配结果。"""

    reply: str
    memory_recalls: list[MemoryRecallHit]
    memory_block: str
    expression_trace: PersonaExpressionTrace = field(default_factory=PersonaExpressionTrace)
    l3_trace: PersonaL3Trace = field(default_factory=PersonaL3Trace)
    l4_trace: PersonaL4Trace = field(default_factory=PersonaL4Trace)
    audit_events: tuple[str, ...] = ()
    pending_audit_events: tuple[str, ...] = ()


@dataclass(frozen=True)
class _L3PromptApplication:
    """摘要：一次生成尝试采用的锁定 prompt 与 L3 trace。"""

    locked_prompt: str
    trace: PersonaL3Trace


@dataclass(frozen=True)
class _FinalizedReply:
    """摘要：算术审计与 L4 动作链完成后的唯一可放行正文。"""

    reply: str
    l3_trace: PersonaL3Trace
    l4_trace: PersonaL4Trace
    audit_events: tuple[str, ...] = ()
    pending_audit_events: tuple[str, ...] = ()


class PersonaSessionCore:
    """摘要：围绕单一人设完成人上下文装配与本地推理调用。"""

    def __init__(
        self,
        persona: Persona,
        semantic_embed_func: Callable[[str], list[float]] | None = None,
        constraint_assets: PersonaConstraintAssets | None = None,
    ) -> None:
        """摘要：初始化会话核心并绑定语义事件 embedding 入口。

        参数：
            persona: 当前会话使用的人格定义。
            semantic_embed_func: 可选的统一语义事件向量函数。
            constraint_assets: 可选的已校验人格约束发布资产。
        """
        self.persona = persona
        self._semantic_embed = semantic_embed_func or SemanticEmbeddingProvider()
        self._constraint_assets = constraint_assets
        self._l3_policy: PersonaL3Policy | None = (
            policy_from_assets(constraint_assets) if constraint_assets is not None else None
        )
        self._l4_policy: PersonaL4Policy | None = (
            l4_policy_from_assets(constraint_assets) if constraint_assets is not None else None
        )

    @property
    def system_prompt_locked(self) -> str:
        """摘要：返回受角色锁约束的系统提示文本（含当前陪伴自称）。"""
        return self._system_prompt_locked()

    def _system_prompt_locked(self, conn: sqlite3.Connection | None = None) -> str:
        """摘要：返回角色锁系统提示；若存在助手画像记忆，优先使用记忆中的当前自称。"""
        return self._identity_prompt_prefix(conn) + self.persona.system_prompt

    def _identity_prompt_prefix(self, conn: sqlite3.Connection | None = None) -> str:
        """摘要：构造与会话快照正文分离的当前自称锁前缀。"""
        display = self._resolved_companion_display_name(conn)
        return (
            f"【当前自称】{display}\n"
            "只有用户主动询问你的名字或身份，或当前语境确实需要时，才提及自称；普通寒暄不要主动自我介绍。\n"
            "需要提及名字时必须使用上述标准自称，不要使用名字变体。\n\n"
        )

    def _resolved_companion_display_name(self, conn: sqlite3.Connection | None = None) -> str:
        """摘要：解析当前助手自称；长期画像记忆优先于 persona 默认配置。"""
        return effective_companion_display_name(self.persona, conn)

    def _turn_signals(
        self,
        emotion_context: EmotionContext | None,
        explicit: PersonaTurnSignals | None,
    ) -> PersonaTurnSignals:
        """摘要：把情绪上下文与调用方审计信号合成单次不可变输入。"""
        audit_events = explicit.audit_events if explicit is not None else ()
        if explicit is not None and (
            explicit.emotion_label is not None or explicit.emotion_confidence is not None
        ):
            return explicit
        if emotion_context is None:
            return PersonaTurnSignals(audit_events=audit_events)
        return PersonaTurnSignals(
            emotion_label=emotion_context.emotion,
            emotion_confidence=emotion_context.confidence,
            audit_events=audit_events,
        )

    def _constraints_managed(self) -> bool:
        """摘要：仅允许当前发布 manifest 下的已验证人格进入 L3/L4。"""
        assets = self._constraint_assets
        raw = self.persona.raw if isinstance(self.persona.raw, dict) else {}
        return bool(
            assets is not None
            and str(raw.get("validation_status") or "") == "validated_anchor"
            and str(raw.get("constraint_manifest_sha256") or "") == assets.manifest_sha256
        )

    def requires_audited_stream_buffering(self) -> bool:
        """摘要：返回当前会话是否必须先完成 L4 审计再放行流式正文。"""
        return self._constraints_managed() and self._l4_policy is not None

    def _apply_l3(
        self,
        conn: sqlite3.Connection,
        signals: PersonaTurnSignals,
    ) -> _L3PromptApplication:
        """摘要：保持标准态快照字节不变，仅为低强度生成临时替换 prompt。"""
        standard_prompt = self._system_prompt_locked(conn)
        assets = self._constraint_assets
        policy = self._l3_policy
        if (
            assets is None
            or policy is None
            or not self._constraints_managed()
        ):
            return _L3PromptApplication(standard_prompt, PersonaL3Trace())

        decision = resolve_l3(signals, policy)
        if decision.result == L3_STANDARD_INTENSITY:
            return _L3PromptApplication(standard_prompt, _trace_from_decision(decision))

        preset = next(
            (item for item in assets.builtin_presets if item.persona_id == self.persona.persona_id),
            None,
        )
        if preset is None:
            return _L3PromptApplication(
                standard_prompt,
                _trace_from_decision(decision, closure_reason="validated_persona_missing"),
            )
        base_prompt = self._identity_prompt_prefix(conn) + preset.base_system_prompt
        if decision.result == L3_INVALID_EMOTION_SIGNAL:
            return _L3PromptApplication(
                base_prompt,
                _trace_from_decision(
                    decision,
                    prompt_replaced=True,
                    closure_reason=L3_INVALID_EMOTION_SIGNAL,
                ),
            )
        if decision.trigger_domain is None:
            return _L3PromptApplication(
                base_prompt,
                _trace_from_decision(decision, prompt_replaced=True, closure_reason="trigger_missing"),
            )
        try:
            mapping = l3_frozen_l1_mapping(
                self.persona.persona_id,
                assets,
                decision.trigger_domain,
            )
            assembled = assemble_l1_prompt(self.persona.persona_id, assets, mapping)
            prompt = finalize_l1_prompt(assembled, self._resolved_companion_display_name(conn))
        except PersonaL1AssemblyError:
            logger.warning("L3 低强度样本不可用，关闭本轮人格约束", exc_info=True)
            return _L3PromptApplication(
                base_prompt,
                _trace_from_decision(
                    decision,
                    prompt_replaced=True,
                    closure_reason="l3_asset_unavailable",
                ),
            )
        return _L3PromptApplication(
            self._identity_prompt_prefix(conn) + prompt,
            _trace_from_decision(
                decision,
                prompt_replaced=True,
                structural_sample_id=mapping.structural_sample_id,
            ),
        )

    def _finalize_generated_reply(
        self,
        backend: InferenceBackend,
        conn: sqlite3.Connection,
        *,
        reply: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int,
        emotion_context: EmotionContext | None,
        capability_profile: CapabilityProfile | None,
        skill_prompt: str,
        expression_config: PersonaExpressionConfig,
        active_signals: PersonaTurnSignals,
        initial_l3_trace: PersonaL3Trace,
        audit_arithmetic: bool,
        audit_event_mirror: Callable[[str, bool], bool] | None,
    ) -> _FinalizedReply:
        """摘要：依次完成算术审计与一次有界 L4 retry/fallback。"""
        final_l3_trace = initial_l3_trace
        audit_events: list[str] = []
        pending_audit_events: list[str] = []

        def on_audit_event(event_type: str) -> bool | None:
            nonlocal active_signals
            active_signals = active_signals.with_audit_event(event_type)
            if audit_event_mirror is None:
                return None
            return audit_event_mirror(
                event_type,
                event_type != AUDIT_ARITHMETIC_WARNING_APPENDED,
            )

        def generate_with_reminder(reminder: str) -> str:
            nonlocal final_l3_trace
            application = self._apply_l3(conn, active_signals)
            final_l3_trace = application.trace
            retry_prompt = self._compose_system_prompt(
                conn,
                emotion_context=emotion_context,
                capability_profile=capability_profile,
                skill_prompt=skill_prompt,
                expression_config=expression_config,
                l3_application=application,
            )
            return backend.generate(
                system_prompt=f"{retry_prompt}\n\n{reminder}",
                history=history,
                user_message=user_message,
                memory_block=memory_block,
                max_tokens=max_tokens,
            )

        def record_audit(result: ArithmeticAuditResult) -> None:
            nonlocal final_l3_trace
            audit_events.extend(result.audit_events)
            if AUDIT_ARITHMETIC_WARNING_APPENDED in result.audit_events:
                pending_audit_events.append(AUDIT_ARITHMETIC_WARNING_APPENDED)
            if result.event_mirror_failures:
                final_l3_trace = replace(final_l3_trace, event_mirror_failed=True)

        audited_reply = str(reply or "")
        if audit_arithmetic:
            audit = audit_arithmetic_reply(
                audited_reply,
                retry=lambda feedback: generate_with_reminder(f"【算术校验反馈】\n{feedback}"),
                on_event=on_audit_event,
            )
            record_audit(audit)
            audited_reply = audit.reply

        policy = self._l4_policy
        if policy is None or not self._constraints_managed():
            return _FinalizedReply(
                reply=audited_reply,
                l3_trace=final_l3_trace,
                l4_trace=PersonaL4Trace(),
                audit_events=tuple(audit_events),
                pending_audit_events=tuple(dict.fromkeys(pending_audit_events)),
            )

        display_name = self._resolved_companion_display_name(conn)
        first = resolve_l4(audited_reply, policy, display_name=display_name)
        if first.action == L4_DIRECT:
            return _FinalizedReply(
                reply=audited_reply,
                l3_trace=final_l3_trace,
                l4_trace=_l4_trace(first, outcome=L4_DIRECT),
                audit_events=tuple(audit_events),
                pending_audit_events=tuple(dict.fromkeys(pending_audit_events)),
            )
        if first.action == L4_OBSERVE:
            return _FinalizedReply(
                reply=audited_reply,
                l3_trace=final_l3_trace,
                l4_trace=_l4_trace(
                    first,
                    outcome=L4_OBSERVE,
                    warnings=(_l4_observe_warning(first),),
                ),
                audit_events=tuple(audit_events),
                pending_audit_events=tuple(dict.fromkeys(pending_audit_events)),
            )

        retry_reply = generate_with_reminder(build_l4_retry_instruction(display_name))
        if audit_arithmetic:
            retry_audit = audit_arithmetic_reply(
                retry_reply,
                retry_allowed=False,
                on_event=on_audit_event,
            )
            record_audit(retry_audit)
            retry_reply = retry_audit.reply
        second = resolve_l4(retry_reply, policy, display_name=display_name)
        if second.action == L4_RETRY:
            return _FinalizedReply(
                reply=deterministic_l4_fallback(first.zone, display_name),
                l3_trace=final_l3_trace,
                l4_trace=_l4_trace(
                    first,
                    outcome=L4_FALLBACK,
                    retry=second,
                    retry_taken=True,
                    warnings=("l4_retry_exhausted",),
                ),
                audit_events=tuple(audit_events),
                pending_audit_events=tuple(dict.fromkeys(pending_audit_events)),
            )
        warnings = (
            (_l4_observe_warning(second),)
            if second.action == L4_OBSERVE
            else ()
        )
        return _FinalizedReply(
            reply=retry_reply,
            l3_trace=final_l3_trace,
            l4_trace=_l4_trace(
                first,
                outcome=L4_RETRY,
                retry=second,
                retry_taken=True,
                warnings=warnings,
            ),
            audit_events=tuple(audit_events),
            pending_audit_events=tuple(dict.fromkeys(pending_audit_events)),
        )

    def assemble_reply(
        self,
        backend: InferenceBackend,
        conn: sqlite3.Connection,
        *,
        user_message: str,
        history: list[MessageRow],
        memory_enabled: bool,
        max_tokens: int = 256,
        reference_block: str = "",
        emotion_context: EmotionContext | None = None,
        capability_profile: CapabilityProfile | None = None,
        skill_prompt: str = "",
        audit_arithmetic: bool = True,
        expression_config: PersonaExpressionConfig | None = None,
        turn_signals: PersonaTurnSignals | None = None,
        audit_event_mirror: Callable[[str, bool], bool] | None = None,
    ) -> AssembleReplyResult:
        """摘要：装配 prompt、注入记忆召回与情绪/语气策略并调用推理后端。"""
        config = expression_config or PersonaExpressionConfig()
        active_signals = self._turn_signals(emotion_context, turn_signals)
        l3_application = self._apply_l3(conn, active_signals)
        final_l3_trace = l3_application.trace
        recalls, combined_memory_block, system_prompt, identity_reply = self._assemble_context(
            conn,
            user_message=user_message,
            memory_enabled=memory_enabled,
            reference_block=reference_block,
            emotion_context=emotion_context,
            capability_profile=capability_profile,
            skill_prompt=skill_prompt,
            expression_config=config,
            turn_signals=active_signals,
            _l3_application=l3_application,
        )
        display_name = self._resolved_companion_display_name(conn)
        identity_reminder = ""
        identity_reminder_injected = False
        if config.identity_near_prompt_enabled and is_identity_intent(user_message):
            identity_reminder = build_identity_reminder(display_name, self.persona)
            user_message = append_ephemeral_identity_reminder(user_message, identity_reminder)
            identity_reminder_injected = True
        if identity_reply is not None:
            return AssembleReplyResult(
                reply=identity_reply,
                memory_recalls=recalls,
                memory_block=combined_memory_block,
                expression_trace=PersonaExpressionTrace(
                    style_block_injected=STYLE_BLOCK_HEADER in system_prompt,
                    identity_reminder_injected=identity_reminder_injected,
                ),
                l3_trace=final_l3_trace,
            )

        reply = backend.generate(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            memory_block=combined_memory_block,
            max_tokens=max_tokens,
        )
        finalized = self._finalize_generated_reply(
            backend,
            conn,
            reply=reply,
            history=history,
            user_message=user_message,
            memory_block=combined_memory_block,
            max_tokens=max_tokens,
            emotion_context=emotion_context,
            capability_profile=capability_profile,
            skill_prompt=skill_prompt,
            expression_config=config,
            active_signals=active_signals,
            initial_l3_trace=final_l3_trace,
            audit_arithmetic=audit_arithmetic,
            audit_event_mirror=audit_event_mirror,
        )
        output_source = "direct"
        retry_taken = False
        retry_generation_cliff = False
        warnings: tuple[str, ...] = ()
        audited_reply = finalized.reply
        first_generation_cliff = (
            not finalized.l4_trace.enabled
            and config.identity_exit_guard_enabled
            and is_identity_intent(user_message)
            and detect_identity_cliff(audited_reply, display_name)
        )
        if first_generation_cliff:
            retry_taken = True
            retry_message = append_ephemeral_identity_reminder(
                user_message,
                build_identity_retry_reminder(display_name),
            )
            retry_reply = backend.generate(
                system_prompt=system_prompt,
                history=history,
                user_message=retry_message,
                memory_block=combined_memory_block,
                max_tokens=max_tokens,
            )
            retry_generation_cliff = detect_identity_cliff(retry_reply, display_name)
            if retry_generation_cliff:
                audited_reply = deterministic_identity_fallback(display_name, self.persona)
                output_source = "fallback"
                warnings = (warn_identity_fallback_once(),)
            else:
                audited_reply = retry_reply
                output_source = "retry"
        return AssembleReplyResult(
            reply=audited_reply,
            memory_recalls=recalls,
            memory_block=combined_memory_block,
            expression_trace=PersonaExpressionTrace(
                style_block_injected=STYLE_BLOCK_HEADER in system_prompt,
                identity_reminder_injected=identity_reminder_injected,
                first_generation_cliff=first_generation_cliff,
                retry_taken=retry_taken,
                retry_generation_cliff=retry_generation_cliff,
                output_source=output_source,
                warnings=warnings,
            ),
            l3_trace=finalized.l3_trace,
            l4_trace=finalized.l4_trace,
            audit_events=finalized.audit_events,
            pending_audit_events=finalized.pending_audit_events,
        )

    def assemble_reply_stream(
        self,
        backend: InferenceBackend,
        conn: sqlite3.Connection,
        *,
        user_message: str,
        history: list[MessageRow],
        memory_enabled: bool,
        max_tokens: int = 256,
        reference_block: str = "",
        emotion_context: EmotionContext | None = None,
        capability_profile: CapabilityProfile | None = None,
        skill_prompt: str = "",
        expression_config: PersonaExpressionConfig | None = None,
        turn_signals: PersonaTurnSignals | None = None,
        audit_event_mirror: Callable[[str, bool], bool] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """摘要：流式生成单轮回复，并在结束事件中返回审计后的最终正文。"""
        config = expression_config or PersonaExpressionConfig()
        active_signals = self._turn_signals(emotion_context, turn_signals)
        l3_application = self._apply_l3(conn, active_signals)
        final_l3_trace = l3_application.trace
        recalls, combined_memory_block, system_prompt, identity_reply = self._assemble_context(
            conn,
            user_message=user_message,
            memory_enabled=memory_enabled,
            reference_block=reference_block,
            emotion_context=emotion_context,
            capability_profile=capability_profile,
            skill_prompt=skill_prompt,
            expression_config=config,
            turn_signals=active_signals,
            _l3_application=l3_application,
        )
        if config.identity_near_prompt_enabled and is_identity_intent(user_message):
            user_message = append_ephemeral_identity_reminder(
                user_message,
                build_identity_reminder(self._resolved_companion_display_name(conn), self.persona),
            )
        yield {"recall": len(recalls)}
        if identity_reply is not None:
            yield {"token": identity_reply}
            yield {
                "done": True,
                "reply": identity_reply,
                "memory_recalls": recalls,
                "l3_trace": final_l3_trace,
                "l4_trace": PersonaL4Trace(),
                "pending_audit_events": (),
            }
            return
        buffered = self.requires_audited_stream_buffering()
        chunks: list[str] = []
        for token in backend.generate_stream(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            memory_block=combined_memory_block,
            max_tokens=max_tokens,
        ):
            chunks.append(token)
            if not buffered:
                yield {"token": token}
        raw_reply = "".join(chunks)
        finalized = self._finalize_generated_reply(
            backend,
            conn,
            reply=raw_reply,
            history=history,
            user_message=user_message,
            memory_block=combined_memory_block,
            max_tokens=max_tokens,
            emotion_context=emotion_context,
            capability_profile=capability_profile,
            skill_prompt=skill_prompt,
            expression_config=config,
            active_signals=active_signals,
            initial_l3_trace=final_l3_trace,
            audit_arithmetic=True,
            audit_event_mirror=audit_event_mirror,
        )
        l4_trace = replace(finalized.l4_trace, buffered=True) if buffered else finalized.l4_trace
        if buffered:
            for token in _buffered_replay_chunks(finalized.reply):
                yield {"token": token}
        yield {
            "done": True,
            "reply": finalized.reply,
            "memory_recalls": recalls,
            "l3_trace": finalized.l3_trace,
            "l4_trace": l4_trace,
            "audit_events": finalized.audit_events,
            "pending_audit_events": finalized.pending_audit_events,
        }

    def _assemble_context(
        self,
        conn: sqlite3.Connection,
        *,
        user_message: str,
        memory_enabled: bool,
        reference_block: str = "",
        emotion_context: EmotionContext | None = None,
        capability_profile: CapabilityProfile | None = None,
        skill_prompt: str = "",
        expression_config: PersonaExpressionConfig | None = None,
        turn_signals: PersonaTurnSignals | None = None,
        _l3_application: _L3PromptApplication | None = None,
    ) -> tuple[list[MemoryRecallHit], str, str, str | None]:
        """摘要：装配召回块、逐轮人格 prompt 与确定性身份回复。"""
        config = expression_config or PersonaExpressionConfig()
        profile = capability_profile or CapabilityProfile()
        recalls: list[MemoryRecallHit] = []
        memory_block = ""
        if reference_block.strip():
            memory_block = reference_block.strip()
        elif memory_enabled:
            emotion_label = emotion_context.emotion if emotion_context is not None else None
            recall_limit = 8 if profile.max_context >= 4096 else 4
            recalls = recall(conn, user_message, limit=recall_limit, emotion=emotion_label)
            memory_block = format_recall_prompt_block(recalls)
            semantic_events = EventRecaller(
                EventRepository(conn),
                embed_func=self._semantic_embed,
            ).recall(
                user_message,
                emotional_context=(
                    {"valence": emotion_context.valence, "arousal": emotion_context.arousal}
                    if emotion_context is not None
                    else None
                ),
                top_k=min(5, recall_limit),
            )
            event_block = format_event_narrative(semantic_events)
            if event_block:
                memory_block = "\n\n".join(part for part in (memory_block, event_block) if part.strip())
        profile_block = self._profile_memory_block(conn) if memory_enabled else ""
        combined_memory_block = "\n\n".join(part for part in (profile_block, memory_block) if part.strip())
        application = _l3_application or self._apply_l3(
            conn,
            self._turn_signals(emotion_context, turn_signals),
        )
        system_prompt = self._compose_system_prompt(
            conn,
            emotion_context=emotion_context,
            capability_profile=profile,
            skill_prompt=skill_prompt,
            expression_config=config,
            l3_application=application,
        )
        if os.getenv("OFFLINE_COMPANION_PROMPT_PROBE") == "1":
            logger.debug("[PROMPT_PROBE] system_prompt=%r", system_prompt[:200])
        identity_reply = self._identity_question_reply(conn, user_message, memory_enabled=memory_enabled)
        return recalls, combined_memory_block, system_prompt, identity_reply

    def _compose_system_prompt(
        self,
        conn: sqlite3.Connection,
        *,
        emotion_context: EmotionContext | None,
        capability_profile: CapabilityProfile | None,
        skill_prompt: str,
        expression_config: PersonaExpressionConfig,
        l3_application: _L3PromptApplication,
    ) -> str:
        """摘要：以给定逐轮 L3 应用结果构造无召回副作用的 system prompt。"""
        del conn
        profile = capability_profile or CapabilityProfile()
        tone_instruction = _build_tone_instruction(self.persona.ocean)
        if profile.roleplay_quality < 0.4:
            tone_instruction = ""
        emotion_instruction = _build_emotion_instruction(emotion_context)
        format_hint = ""
        if profile.instruction_following < 0.4:
            format_hint = "\n【输出要求】请用简洁自然的中文回答，不要重复用户的话。\n"
        prompt_parts = [
            l3_application.locked_prompt,
            "涉及数值计算时，给出结果前先做量级估算复核。",
            SKILL_BOOTSTRAP_PROMPT,
        ]
        if skill_prompt.strip():
            prompt_parts.append(skill_prompt.strip())
        if expression_config.style_examples_enabled:
            style_block = build_style_examples_block(self.persona)
            if style_block:
                prompt_parts.append(style_block)
        return "\n\n".join(prompt_parts) + (
            tone_instruction + emotion_instruction + format_hint
        )

    def _profile_memory_block(self, conn: sqlite3.Connection) -> str:
        profile = MemoryLifecycleManager.latest_profile_memory(conn)
        lines: list[str] = []
        assistant = profile.get("assistant", {})
        user = profile.get("user", {})
        if assistant.get("display_name"):
            display_name = _sanitize_display_name(assistant["display_name"])
            if display_name:
                lines.append(f"- 助手当前自画像：名字 = {display_name}")
        if user.get("display_name"):
            lines.append(f"- 用户当前画像：名字 = {user['display_name']}")
        if user.get("preference"):
            lines.append(f"- 用户长期偏好：{user['preference']}")
        if not lines:
            return ""
        return "【长期画像记忆】\n" + "\n".join(lines)

    def _identity_question_reply(self, conn: sqlite3.Connection, user_message: str, *, memory_enabled: bool) -> str | None:
        """摘要：对助手自称查询做确定性回答，避免小模型忽略画像身份锁。"""
        if not memory_enabled:
            return None
        text = user_message.strip()
        if not any(keyword in text for keyword in _ASSISTANT_NAME_QUESTION_KEYWORDS):
            return None
        display_name = self._resolved_companion_display_name(conn)
        if not display_name:
            return None
        return f"我叫{display_name}。"
