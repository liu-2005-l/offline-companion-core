"""inference_backend：C1 本地推理后端。"""

from offline_companion.runtime.inference_backend.backend import (
    InferenceBackend,
    InferenceHealthReport,
    LlamaCppBackend,
    create_llama_backend,
    resolve_gguf_path,
    try_stderr_cuda_hint,
)
from offline_companion.runtime.inference_backend.mock import EchoBackend

check_model = LlamaCppBackend.check_model

__all__ = [
    "EchoBackend",
    "InferenceBackend",
    "InferenceHealthReport",
    "LlamaCppBackend",
    "check_model",
    "create_llama_backend",
    "resolve_gguf_path",
    "try_stderr_cuda_hint",
]
