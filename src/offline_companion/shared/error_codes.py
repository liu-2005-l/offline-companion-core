"""摘要：跨层结构化错误码定义。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class ErrorCodeSpec:
    """摘要：单个错误码的结构化元数据。"""

    code: str
    source: str
    recoverable: bool
    message_template: str


class ErrorCode(Enum):
    """摘要：系统错误码枚举。"""

    E_A2_PLAN_VALIDATION_FAILED = ErrorCodeSpec(
        "E_A2_PLAN_VALIDATION_FAILED",
        "A2",
        False,
        "计划模板或依赖校验失败。",
    )
    E_A2_PLAN_EXECUTION_FAILED = ErrorCodeSpec(
        "E_A2_PLAN_EXECUTION_FAILED",
        "A2",
        True,
        "计划执行失败。",
    )
    E_A2_PLAN_TEMPLATE_NOT_FOUND = ErrorCodeSpec(
        "E_A2_PLAN_TEMPLATE_NOT_FOUND",
        "A2",
        False,
        "计划模板不存在。",
    )
    E_A2_STATE_ACCESS_DENIED = ErrorCodeSpec(
        "E_A2_STATE_ACCESS_DENIED",
        "A2",
        False,
        "状态域访问被拒绝。",
    )
    E_A2_STATE_VERSION_CONFLICT = ErrorCodeSpec(
        "E_A2_STATE_VERSION_CONFLICT",
        "A2",
        True,
        "状态版本冲突。",
    )
    E_A2_STATE_EVENT_INVALID = ErrorCodeSpec(
        "E_A2_STATE_EVENT_INVALID",
        "A2",
        False,
        "状态事件格式不合法。",
    )
    E_SKILL_HASH_MISSING = ErrorCodeSpec(
        "E_SKILL_HASH_MISSING",
        "A2",
        False,
        "Skill 依赖缺少哈希锁定，已拒绝启动。",
    )
    E_SKILL_HASH_MISMATCH = ErrorCodeSpec(
        "E_SKILL_HASH_MISMATCH",
        "A2",
        False,
        "Skill 完整性校验失败，已拒绝启动。",
    )
    E_SKILL_BUILTIN_HASH_MISSING = ErrorCodeSpec(
        "E_SKILL_BUILTIN_HASH_MISSING",
        "A2",
        False,
        "内置 Skill 缺少完整性清单，已拒绝启动。",
    )
    E_SKILL_BUILTIN_HASH_MISMATCH = ErrorCodeSpec(
        "E_SKILL_BUILTIN_HASH_MISMATCH",
        "A2",
        False,
        "内置 Skill 文件完整性校验失败，已拒绝启动。",
    )
    E_SKILL_TRUST_ANCHOR_MISSING = ErrorCodeSpec(
        "E_SKILL_TRUST_ANCHOR_MISSING",
        "A2",
        False,
        "宿主侧信任锚缺失，已拒绝启动内置 Skill。",
    )
    E_B0_EMOTION_MODEL_LOAD_FAILED = ErrorCodeSpec(
        "E_EMOTION_MODEL_LOAD_FAILED",
        "B0",
        True,
        "情绪模型加载失败，已回退到无情绪上下文。",
    )
    E_B0_EMOTION_INFERENCE_TIMEOUT = ErrorCodeSpec(
        "E_EMOTION_INFERENCE_TIMEOUT",
        "B0",
        True,
        "情绪推理超时，已回退到无情绪上下文。",
    )
    E_B0_EMOTION_TOKENIZER_ERROR = ErrorCodeSpec(
        "E_EMOTION_TOKENIZER_ERROR",
        "B0",
        True,
        "情绪 tokenizer 处理失败，已回退到无情绪上下文。",
    )
    E_B0_EMOTION_CONFIDENCE_LOW = ErrorCodeSpec(
        "E_EMOTION_CONFIDENCE_LOW",
        "B0",
        True,
        "情绪置信度不足，已回退到 neutral。",
    )
    E_B1_PERSONA_ASSEMBLE_FAILED = ErrorCodeSpec(
        "E_B1_PERSONA_ASSEMBLE_FAILED",
        "B1",
        True,
        "人格会话装配失败。",
    )
    E_B2_RECALL_FAILED = ErrorCodeSpec(
        "E_B2_RECALL_FAILED",
        "B2",
        True,
        "记忆召回失败。",
    )
    E_B2_MEMORY_WRITE_FAILED = ErrorCodeSpec(
        "E_B2_MEMORY_WRITE_FAILED",
        "B2",
        False,
        "记忆写入参数非法或落库失败。",
    )
    E_B2_TRIGGER_CONFIG_INVALID = ErrorCodeSpec(
        "E_B2_TRIGGER_CONFIG_INVALID",
        "B2",
        False,
        "触发器配置无效。",
    )
    E_B2_TRIGGER_CONFIG_MISSING = ErrorCodeSpec(
        "E_B2_TRIGGER_CONFIG_MISSING",
        "B2",
        False,
        "触发器配置缺失。",
    )
    E_B3_SECURITY_BLOCKED = ErrorCodeSpec(
        "E_B3_SECURITY_BLOCKED",
        "B3",
        False,
        "内容安全边界阻断本轮请求。",
    )
    E_B3_REPLIES_CONFIG_INVALID = ErrorCodeSpec(
        "E_B3_REPLIES_CONFIG_INVALID",
        "B3",
        False,
        "安全话术库格式无效。",
    )
    E_B3_REPLIES_CONFIG_MISSING = ErrorCodeSpec(
        "E_B3_REPLIES_CONFIG_MISSING",
        "B3",
        False,
        "安全话术库缺失。",
    )
    E_B4_REFORMAT_FAILED = ErrorCodeSpec(
        "E_B4_REFORMAT_FAILED",
        "B4",
        True,
        "输出润色失败，需走本地降级或固定话术。",
    )
    E_C1_INFERENCE_BACKEND_FAILED = ErrorCodeSpec(
        "E_C1_INFERENCE_BACKEND_FAILED",
        "C1",
        True,
        "推理后端不可用或生成失败。",
    )
    E_C2_BUNDLE_FORMAT_INVALID = ErrorCodeSpec(
        "E_C2_BUNDLE_FORMAT_INVALID",
        "C2",
        False,
        "导出包格式非法或版本不兼容。",
    )

    @property
    def code(self) -> str:
        return self.value.code

    @property
    def source(self) -> str:
        return self.value.source

    @property
    def recoverable(self) -> bool:
        return self.value.recoverable

    @property
    def message_template(self) -> str:
        return self.value.message_template


def error_log_fields(exc: BaseException) -> dict[str, Any]:
    """摘要：将异常转换为可结构化查询的日志字段。"""
    error_code = getattr(exc, "error_code", None)
    if isinstance(error_code, ErrorCode):
        return {
            "error_code": error_code.code,
            "source": error_code.source,
            "recoverable": error_code.recoverable,
            "message_template": error_code.message_template,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
    return {
        "error_code": None,
        "source": None,
        "recoverable": None,
        "message_template": None,
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
