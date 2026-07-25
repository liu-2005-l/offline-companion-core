"""测试：结构化 ErrorCode 框架。"""

from __future__ import annotations

from offline_companion.shared.error_codes import ErrorCode, error_log_fields
from offline_companion.shared.errors import (
    B0EmotionConfidenceLow,
    B0EmotionInferenceTimeout,
    B0EmotionModelLoadError,
    B0EmotionTokenizerError,
    B2RecallError,
    B3SecurityError,
    ReformatError,
)


def test_b_layer_errors_carry_error_code() -> None:
    """B 层异常应携带可聚合的 ErrorCode。"""
    errors = [
        B2RecallError("recall failed"),
        B3SecurityError("blocked"),
        ReformatError("bad output"),
    ]
    for exc in errors:
        assert isinstance(exc.error_code, ErrorCode)
        fields = error_log_fields(exc)
        assert fields["error_code"] == exc.error_code.code
        assert fields["source"] == exc.error_code.source


def test_b0_reserved_error_codes_are_recoverable() -> None:
    """B0 预留错误码应标记可恢复，供后续 fallback 接入。"""
    errors = [
        B0EmotionModelLoadError("load"),
        B0EmotionInferenceTimeout("timeout"),
        B0EmotionTokenizerError("tokenizer"),
        B0EmotionConfidenceLow("low"),
    ]
    for exc in errors:
        assert exc.error_code.source == "B0"
        assert exc.error_code.recoverable is True
        assert error_log_fields(exc)["error_code"] == exc.error_code.code
