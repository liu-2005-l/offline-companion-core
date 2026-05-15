"""backend：可选 GGUF 推理实现（依赖 llama-cpp-python 可选安装）。"""

from __future__ import annotations

import sys
from typing import Protocol, runtime_checkable

from offline_companion.shared.types import MessageRow


@runtime_checkable
class InferenceBackend(Protocol):
    """摘要：本地推理后端协议。"""

    def generate(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> str: ...


class LlamaCppBackend:
    """摘要：基于 llama-cpp-python 的 GGUF 后端。"""

    def __init__(
        self,
        model_path: str,
        *,
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        verbose: bool = False,
    ) -> None:
        try:
            from llama_cpp import Llama  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "llama-cpp-python is not installed. Install with:\n"
                "  pip install '.[inference]'\n"
                "On Windows with NVIDIA CUDA wheels, follow upstream docs for the matching wheel."
            ) from e

        self._llama = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose,
        )

    def generate(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> str:
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if memory_block.strip():
            messages.append({"role": "system", "content": memory_block})
        for m in history:
            if m.role in ("user", "assistant"):
                messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": user_message})
        out = self._llama.create_chat_completion(messages=messages, max_tokens=max_tokens)
        choice = out["choices"][0]
        msg = choice.get("message") or {}
        content = msg.get("content")
        if not content:
            raise RuntimeError(f"Unexpected llama.cpp response: {out!r}")
        return str(content).strip()


def try_stderr_cuda_hint() -> None:
    """摘要：向 stderr 输出 CUDA 体验提示（不改变控制流）。"""
    print(
        "Tip (Windows / NVIDIA): for best experience use a CUDA-enabled `llama-cpp-python` build "
        "and set `n_gpu_layers` > 0 when constructing `LlamaCppBackend`.",
        file=sys.stderr,
    )
