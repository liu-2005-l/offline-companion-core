"""摘要：跨层异常类型。"""

from __future__ import annotations

from offline_companion.shared.error_codes import ErrorCode


class ErrorCodeMixin:
    """摘要：为异常类型提供结构化 ErrorCode。"""

    error_code: ErrorCode

    def to_log_fields(self) -> dict[str, object]:
        from offline_companion.shared.error_codes import error_log_fields

        return error_log_fields(self)


class BundleFormatError(ErrorCodeMixin, ValueError):
    error_code = ErrorCode.E_C2_BUNDLE_FORMAT_INVALID


class ConsentArtifactError(ValueError):
    """摘要：Consent Artifact 未通过结构校验。"""


class OutboundDenied(RuntimeError):
    """摘要：当前策略或用户选择不允许出站。"""


class InferenceBackendError(ErrorCodeMixin, RuntimeError):
    error_code = ErrorCode.E_C1_INFERENCE_BACKEND_FAILED


class ReformatError(ErrorCodeMixin, ValueError):
    error_code = ErrorCode.E_B4_REFORMAT_FAILED


class B1PersonaAssembleError(ErrorCodeMixin, RuntimeError):
    error_code = ErrorCode.E_B1_PERSONA_ASSEMBLE_FAILED


class A2PlanValidationError(ErrorCodeMixin, ValueError):
    error_code = ErrorCode.E_A2_PLAN_VALIDATION_FAILED


class A2PlanExecutionError(ErrorCodeMixin, RuntimeError):
    error_code = ErrorCode.E_A2_PLAN_EXECUTION_FAILED


class A2PlanTemplateNotFoundError(ErrorCodeMixin, FileNotFoundError):
    error_code = ErrorCode.E_A2_PLAN_TEMPLATE_NOT_FOUND


class B2RecallError(ErrorCodeMixin, RuntimeError):
    error_code = ErrorCode.E_B2_RECALL_FAILED


class B2MemoryWriteError(ErrorCodeMixin, ValueError):
    error_code = ErrorCode.E_B2_MEMORY_WRITE_FAILED


class B2TriggerConfigError(ErrorCodeMixin, ValueError):
    error_code = ErrorCode.E_B2_TRIGGER_CONFIG_INVALID


class B2TriggerConfigNotFoundError(ErrorCodeMixin, FileNotFoundError):
    error_code = ErrorCode.E_B2_TRIGGER_CONFIG_MISSING


class B3SecurityError(ErrorCodeMixin, RuntimeError):
    error_code = ErrorCode.E_B3_SECURITY_BLOCKED


class B3RepliesConfigError(ErrorCodeMixin, ValueError):
    error_code = ErrorCode.E_B3_REPLIES_CONFIG_INVALID


class B3RepliesConfigNotFoundError(ErrorCodeMixin, FileNotFoundError):
    error_code = ErrorCode.E_B3_REPLIES_CONFIG_MISSING


class B0EmotionModelLoadError(ErrorCodeMixin, RuntimeError):
    error_code = ErrorCode.E_B0_EMOTION_MODEL_LOAD_FAILED


class B0EmotionInferenceTimeout(ErrorCodeMixin, TimeoutError):
    error_code = ErrorCode.E_B0_EMOTION_INFERENCE_TIMEOUT


class B0EmotionTokenizerError(ErrorCodeMixin, RuntimeError):
    error_code = ErrorCode.E_B0_EMOTION_TOKENIZER_ERROR


class B0EmotionConfidenceLow(ErrorCodeMixin, RuntimeError):
    error_code = ErrorCode.E_B0_EMOTION_CONFIDENCE_LOW


class CloudConnectorError(RuntimeError):
    """摘要：A3 出站 HTTP 调用失败。"""


class SkillManifestError(ValueError):
    """摘要：Skill manifest 未通过校验。"""


class SkillPolicyDenied(RuntimeError):
    """摘要：当前隐私模式或策略不允许启用或调用 Skill。"""


class SkillInvocationError(RuntimeError):
    """摘要：Skill 进程启动、调用或鉴权失败。"""


class SkillSupplyChainError(ErrorCodeMixin, SkillInvocationError):
    """摘要：Skill 供应链校验失败。"""


class SkillHashMissingError(SkillSupplyChainError):
    error_code = ErrorCode.E_SKILL_HASH_MISSING


class SkillHashMismatchError(SkillSupplyChainError):
    error_code = ErrorCode.E_SKILL_HASH_MISMATCH


class SkillBuiltinHashMissingError(SkillSupplyChainError):
    error_code = ErrorCode.E_SKILL_BUILTIN_HASH_MISSING


class SkillBuiltinHashMismatchError(SkillSupplyChainError):
    error_code = ErrorCode.E_SKILL_BUILTIN_HASH_MISMATCH


class SkillTrustAnchorMissingError(SkillSupplyChainError):
    error_code = ErrorCode.E_SKILL_TRUST_ANCHOR_MISSING


class SkillSourceValidationError(SkillInvocationError):
    """摘要：Skill 请求来源 PID 校验失败。"""


class CircuitBreakerOpenError(RuntimeError):
    """摘要：目标服务熔断已打开。"""


class CheckImportsError(RuntimeError):
    """摘要：分层或危险导入检查未通过。"""
