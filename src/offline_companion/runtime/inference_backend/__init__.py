"""inference_backend：C1 本地推理后端。"""

from offline_companion.runtime.inference_backend.backend import (
    InferenceBackend,
    InferenceHealthReport,
    LlamaCppBackend,
    create_llama_backend,
    resolve_gguf_path,
    try_stderr_cuda_hint,
)
from offline_companion.runtime.inference_backend.llama_server_backend import LlamaServerStartupError
from offline_companion.runtime.inference_backend.mock import EchoBackend


def check_model(
    model_path,
    *,
    n_ctx: int = 512,
    n_gpu_layers: int = 0,
    load_model: bool = True,
    probe_generate: bool = False,
):
    """摘要：按运行环境选择进程内或独立服务模型检查。"""
    import sys

    if getattr(sys, "frozen", False):
        from offline_companion.runtime.inference_backend.llama_server_backend import (
            check_llama_server_model,
        )

        return check_llama_server_model(
            model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            probe_generate=probe_generate,
        )
    return LlamaCppBackend.check_model(
        model_path,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        load_model=load_model,
        probe_generate=probe_generate,
    )

__all__ = [
    "EchoBackend",
    "InferenceBackend",
    "InferenceHealthReport",
    "LlamaCppBackend",
    "LlamaServerStartupError",
    "check_model",
    "create_llama_backend",
    "resolve_gguf_path",
    "try_stderr_cuda_hint",
]
