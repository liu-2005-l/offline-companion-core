"""摘要：人格约束 L3 逐轮触发谓词与不可变信号结构。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any, Literal

from offline_companion.core.persona_constraint.assets import PersonaConstraintAssets

AUDIT_ARITHMETIC_RETRY_TAKEN = "audit/arithmetic_retry_taken"
AUDIT_ARITHMETIC_WARNING_APPENDED = "audit/arithmetic_warning_appended"
AUDIT_QUALITY_RETRY_TAKEN = "audit/quality_retry_taken"
PERSONA_TURN_SIGNALS_PAYLOAD_KEY = "_persona_turn_signals"

L3_STANDARD_INTENSITY = "standard_intensity"
L3_LOW_INTENSITY_COMFORT = "low_intensity_comfort"
L3_LOW_INTENSITY_CORRECTION = "low_intensity_correction"
L3_INVALID_EMOTION_SIGNAL = "invalid_emotion_signal"

L3Result = Literal[
    "standard_intensity",
    "low_intensity_comfort",
    "low_intensity_correction",
    "invalid_emotion_signal",
]


class PersonaL3ConfigError(RuntimeError):
    """摘要：L3 冻结配置缺失或结构不符合机器契约。"""


@dataclass(frozen=True)
class PersonaTurnSignals:
    """摘要：一次模型生成尝试消费的情绪与审计直接信号。"""

    emotion_label: str | None = None
    emotion_confidence: object | None = None
    audit_events: tuple[str, ...] = ()

    def with_audit_event(self, event_type: str) -> PersonaTurnSignals:
        """摘要：返回追加一个审计事实后的新信号对象。"""
        normalized = str(event_type).strip()
        if not normalized or normalized in self.audit_events:
            return self
        return PersonaTurnSignals(
            emotion_label=self.emotion_label,
            emotion_confidence=self.emotion_confidence,
            audit_events=(*self.audit_events, normalized),
        )

    def to_payload(self) -> dict[str, Any]:
        """摘要：生成可跨计划调用边界传递的 JSON 兼容载荷。"""
        return {
            "emotion_label": self.emotion_label,
            "emotion_confidence": self.emotion_confidence,
            "audit_events": list(self.audit_events),
        }

    @classmethod
    def from_payload(cls, payload: object) -> PersonaTurnSignals:
        """摘要：从计划调用载荷恢复信号；非法形态保留给谓词统一判定。"""
        if not isinstance(payload, dict):
            return cls()
        raw_events = payload.get("audit_events")
        events = (
            tuple(str(item) for item in raw_events if isinstance(item, str) and item)
            if isinstance(raw_events, list)
            else ()
        )
        label = payload.get("emotion_label")
        return cls(
            emotion_label=label if isinstance(label, str) else None,
            emotion_confidence=payload.get("emotion_confidence"),
            audit_events=events,
        )


@dataclass(frozen=True)
class PersonaL3Policy:
    """摘要：从第七源冻结资产解析出的 L3 阈值、标签与审计白名单。"""

    accepted_confidence_floor: float
    full_intensity_threshold: float
    empathy_sensitive_labels: tuple[str, ...]
    audit_event_whitelist: tuple[str, ...]


@dataclass(frozen=True)
class PersonaL3Decision:
    """摘要：L3 纯谓词的确定性结果与不进入模型文本的 trace。"""

    result: L3Result
    constraints_enabled: bool
    trace_code: str
    trigger_domain: str | None = None
    audit_event: str | None = None


@dataclass(frozen=True)
class PersonaL3Trace:
    """摘要：逐轮 L3 决策的应用结果，不进入模型文本或会话快照。"""

    result: L3Result = L3_STANDARD_INTENSITY
    trace_code: str = "l3_unmanaged"
    constraints_enabled: bool = True
    prompt_replaced: bool = False
    structural_sample_id: str | None = None
    audit_event: str | None = None
    closure_reason: str | None = None
    event_mirror_failed: bool = False


def policy_from_assets(assets: PersonaConstraintAssets) -> PersonaL3Policy:
    """摘要：从已通过发布哈希校验的第七源构造 L3 策略。"""
    payload = assets.source_payloads.get("downgrade")
    if not isinstance(payload, dict):
        raise PersonaL3ConfigError("persona_l3_downgrade_source_missing")
    emotion = payload.get("emotion_context")
    audit = payload.get("audit_events")
    if not isinstance(emotion, dict) or not isinstance(audit, dict):
        raise PersonaL3ConfigError("persona_l3_policy_invalid")
    labels = emotion.get("empathy_sensitive_labels")
    whitelist = audit.get("whitelist")
    if not isinstance(labels, list) or not all(isinstance(item, str) and item for item in labels):
        raise PersonaL3ConfigError("persona_l3_labels_invalid")
    if not isinstance(whitelist, dict) or not whitelist:
        raise PersonaL3ConfigError("persona_l3_audit_whitelist_invalid")
    try:
        floor = float(emotion["accepted_confidence_floor"])
        full = float(emotion["full_intensity_threshold"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PersonaL3ConfigError("persona_l3_threshold_invalid") from exc
    if not 0.0 <= floor < full <= 1.0:
        raise PersonaL3ConfigError("persona_l3_threshold_invalid")
    events = tuple(str(item) for item in whitelist)
    expected_events = {
        AUDIT_ARITHMETIC_RETRY_TAKEN,
        AUDIT_ARITHMETIC_WARNING_APPENDED,
        AUDIT_QUALITY_RETRY_TAKEN,
    }
    if set(events) != expected_events:
        raise PersonaL3ConfigError("persona_l3_audit_whitelist_invalid")
    return PersonaL3Policy(
        accepted_confidence_floor=floor,
        full_intensity_threshold=full,
        empathy_sensitive_labels=tuple(labels),
        audit_event_whitelist=events,
    )


def resolve_l3(signals: PersonaTurnSignals, policy: PersonaL3Policy) -> PersonaL3Decision:
    """摘要：按冻结阈值、审计优先级与非法值契约解析单次 L3 决策。"""
    confidence, invalid = _validated_confidence(signals)
    if invalid:
        return PersonaL3Decision(
            result=L3_INVALID_EMOTION_SIGNAL,
            constraints_enabled=False,
            trace_code=L3_INVALID_EMOTION_SIGNAL,
        )

    audit_event = next(
        (event for event in policy.audit_event_whitelist if event in signals.audit_events),
        None,
    )
    if audit_event is not None:
        return PersonaL3Decision(
            result=L3_LOW_INTENSITY_CORRECTION,
            constraints_enabled=True,
            trace_code="audit_trigger",
            trigger_domain=L3_LOW_INTENSITY_CORRECTION,
            audit_event=audit_event,
        )

    if confidence is None:
        return PersonaL3Decision(
            result=L3_STANDARD_INTENSITY,
            constraints_enabled=True,
            trace_code="standard_missing_emotion",
        )
    label = signals.emotion_label if isinstance(signals.emotion_label, str) else ""
    if label not in policy.empathy_sensitive_labels:
        return PersonaL3Decision(
            result=L3_STANDARD_INTENSITY,
            constraints_enabled=True,
            trace_code="standard_unlisted_emotion",
        )
    if confidence < policy.accepted_confidence_floor:
        return PersonaL3Decision(
            result=L3_STANDARD_INTENSITY,
            constraints_enabled=True,
            trace_code="standard_below_floor",
        )
    if confidence < policy.full_intensity_threshold:
        return PersonaL3Decision(
            result=L3_LOW_INTENSITY_COMFORT,
            constraints_enabled=True,
            trace_code="emotion_trigger",
            trigger_domain=L3_LOW_INTENSITY_COMFORT,
        )
    return PersonaL3Decision(
        result=L3_STANDARD_INTENSITY,
        constraints_enabled=True,
        trace_code="standard_full_intensity",
    )


def _validated_confidence(signals: PersonaTurnSignals) -> tuple[float | None, bool]:
    if signals.emotion_label is None and signals.emotion_confidence is None:
        return None, False
    value = signals.emotion_confidence
    if isinstance(value, bool) or not isinstance(value, Real):
        return None, True
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        return None, True
    return normalized, False
