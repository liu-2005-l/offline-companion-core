"""backend：C1 本地 GGUF 推理（llama-cpp-python 可选依赖）。"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from offline_companion.shared.errors import InferenceBackendError
from offline_companion.shared.types import MessageRow, ModelRuntimeConfig


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

    def health_check(self) -> InferenceHealthReport:
        """摘要：返回当前后端健康状态（已加载实例应返回 ok）。"""
        ...


@dataclass(frozen=True)
class InferenceHealthReport:
    """摘要：推理后端健康检查结果。

    参数：
        ok: 是否通过检查。
        model_path: 规范化后的模型路径字符串。
        message: 人类可读说明（中文）。
        backend: 后端标识，如 ``llama_cpp``。
    """

    ok: bool
    model_path: str
    message: str
    backend: str = "llama_cpp"


def resolve_gguf_path(model_path: str | Path) -> Path:
    """摘要：解析并校验 GGUF 模型路径。

    参数：
        model_path: 用户提供的模型文件路径。

    返回值：
        已 resolve 的 ``Path``。

    异常：
        InferenceBackendError：路径不存在或后缀非 ``.gguf``。
    """
    path = Path(model_path).expanduser().resolve()
    if not path.is_file():
        raise InferenceBackendError(f"模型文件不存在: {path}")
    if path.suffix.lower() != ".gguf":
        raise InferenceBackendError(f"需要 .gguf 文件，当前为: {path.name}")
    return path


def _import_llama():
    """摘要：延迟导入 `llama_cpp`，并给出更准确的依赖错误提示。"""
    # DLL路径由PyInstaller运行时钩子处理，这里不做额外处理
    # 避免与llama-cpp-python内部的DLL加载机制冲突

    try:
        import numpy  # noqa: F401
    except ImportError as e:  # pragma: no cover - 依赖环境问题
        raise InferenceBackendError(
            f"numpy 加载失败（可能是 MKL / DLL 问题）: {e}\n"
            "建议使用 venv 隔离环境: python -m venv .venv && pip install -e ."
        ) from e

    try:
        from llama_cpp import Llama  # type: ignore
    except ImportError as e:  # pragma: no cover - 可选依赖缺失或其子依赖损坏
        missing_name = str(getattr(e, "name", "") or "")
        if "llama" in missing_name.lower():
            raise InferenceBackendError(
                "未安装 llama-cpp-python。请执行: pip install '.[inference]'\n"
                "Windows + NVIDIA 请选用与驱动匹配的 CUDA wheel。"
            ) from e
        raise InferenceBackendError(
            f"llama-cpp-python 已安装但依赖加载失败: {e}\n"
            "常见原因: numpy / MKL / DLL 冲突，建议用 venv 隔离环境。"
        ) from e
    return Llama

class LlamaCppBackend:
    """摘要：基于 llama-cpp-python 的 GGUF 本地推理后端（C1）。"""

    def __init__(
        self,
        model_path: str | Path,
        *,
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        verbose: bool = False,
        skip_load: bool = False,
        model_config: ModelRuntimeConfig | None = None,
    ) -> None:
        """摘要：加载 GGUF 模型。

        参数：
            model_path: GGUF 文件路径。
            n_ctx: 上下文长度。
            n_gpu_layers: GPU 卸载层数（0 为 CPU）。
            verbose: 是否输出 llama.cpp 详细日志。
            skip_load: 仅用于测试；为 True 时不实例化 Llama（勿在生产使用）。
        """
        self.model_path = resolve_gguf_path(model_path)
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.model_config = model_config or ModelRuntimeConfig(model_id=self.model_path.stem)
        self._llama = None
        if skip_load:
            return
        Llama = _import_llama()
        self._llama = Llama(
            model_path=str(self.model_path),
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose,
        )

    @staticmethod
    def check_model(
        model_path: str | Path,
        *,
        n_ctx: int = 512,
        n_gpu_layers: int = 0,
        load_model: bool = True,
        probe_generate: bool = False,
    ) -> InferenceHealthReport:
        """摘要：启动前检查模型路径与 llama-cpp 是否可用（可不构造长期实例）。

        参数：
            model_path: GGUF 路径。
            n_ctx: 探测加载用的上下文（宜偏小以加快检查）。
            n_gpu_layers: GPU 层数。
            load_model: 为 False 时仅校验路径与依赖导入（不实例化，避免与随后构造重复加载）。
            probe_generate: 为 True 且 ``load_model`` 时额外执行极短 generate。

        返回值：
            ``InferenceHealthReport``；``ok=False`` 时 ``message`` 含原因。
        """
        try:
            path = resolve_gguf_path(model_path)
        except InferenceBackendError as e:
            return InferenceHealthReport(
                ok=False,
                model_path=str(model_path),
                message=str(e),
            )

        try:
            Llama = _import_llama()
        except InferenceBackendError as e:
            return InferenceHealthReport(
                ok=False,
                model_path=str(path),
                message=str(e),
            )

        if not load_model:
            return InferenceHealthReport(
                ok=True,
                model_path=str(path),
                message="路径与 llama-cpp-python 依赖检查通过（尚未加载权重）",
            )

        try:
            print(f"[DEBUG] Loading model from: {path}", file=sys.stderr)
            print(f"[DEBUG] Model file exists: {path.exists()}", file=sys.stderr)
            print(f"[DEBUG] Model file size: {path.stat().st_size if path.exists() else 'N/A'}", file=sys.stderr)
            llama = Llama(
                model_path=str(path),
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                verbose=True,  # Enable verbose to see llama_cpp debug output
            )
            print("[DEBUG] Model loaded successfully", file=sys.stderr)
        except Exception as e:  # pragma: no cover - 依赖具体 wheel/驱动
            print(f"[DEBUG] Exception during model loading: {type(e).__name__}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return InferenceHealthReport(
                ok=False,
                model_path=str(path),
                message=f"加载模型失败: {e}",
            )

        if probe_generate:
            try:
                out = llama.create_chat_completion(
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=8,
                )
                choice = out.get("choices") or []
                if not choice:
                    return InferenceHealthReport(
                        ok=False,
                        model_path=str(path),
                        message="探测生成失败: 响应无 choices",
                    )
            except Exception as e:  # pragma: no cover
                return InferenceHealthReport(
                    ok=False,
                    model_path=str(path),
                    message=f"探测生成失败: {e}",
                )

        return InferenceHealthReport(
            ok=True,
            model_path=str(path),
            message=f"模型已就绪 (n_ctx={n_ctx}, n_gpu_layers={n_gpu_layers})",
        )

    def instance_health_check(self) -> InferenceHealthReport:
        """摘要：检查已加载实例是否可用。"""
        if self._llama is None:
            return InferenceHealthReport(
                ok=False,
                model_path=str(self.model_path),
                message="后端未加载模型实例",
            )
        return InferenceHealthReport(
            ok=True,
            model_path=str(self.model_path),
            message=f"已加载 (n_ctx={self.n_ctx}, n_gpu_layers={self.n_gpu_layers})",
        )

    def health_check(self) -> InferenceHealthReport:
        """摘要：实现 ``InferenceBackend`` 约定的实例健康检查。"""
        return self.instance_health_check()

    def generate(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> str:
        """摘要：按聊天消息列表调用本地模型并返回助手回复文本。"""
        if self._llama is None:
            raise InferenceBackendError("模型未加载，无法 generate")

        messages = self._build_messages(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            memory_block=memory_block,
        )


        try:
            kwargs = {"messages": messages, "max_tokens": max_tokens}
            if self.model_config.stop_tokens:
                kwargs["stop"] = list(self.model_config.stop_tokens)
            out = self._llama.create_chat_completion(**kwargs)
        except Exception as e:  # pragma: no cover
            raise InferenceBackendError(f"推理失败: {e}") from e

        choices = out.get("choices") or []
        if not choices:
            raise InferenceBackendError(f"推理响应异常: {out!r}")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if not content:
            raise InferenceBackendError(f"推理响应无内容: {out!r}")
        return strip_model_output(str(content).strip(), self.model_config)


    def _build_messages(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
    ) -> list[dict[str, str]]:
        """摘要：将 B1 装配出的消息列表转换为 C1 所需的消息格式。"""
        full_system = system_prompt.rstrip()
        if memory_block.strip():
            full_system = f"{full_system}\n\n{memory_block.strip()}"
        messages: list[dict[str, str]] = []
        if full_system.strip():
            if self.model_config.supports_system_role:
                messages.append({"role": "system", "content": full_system})
            else:
                messages.append({"role": "user", "content": full_system})
        for message in history:
            if message.role in ("user", "assistant"):
                messages.append({"role": message.role, "content": message.content})
        messages.append({"role": "user", "content": user_message})
        return messages


def strip_model_output(text: str, model_config: ModelRuntimeConfig) -> str:
    """摘要：按模型配置剥离输出中的包装标签与思考标记。"""
    cleaned = text
    for tag in model_config.strip_output_tags:
        tag_name = tag.strip().strip("<>/")
        if not tag_name:
            continue
        cleaned = re.sub(
            rf"<{re.escape(tag_name)}\b[^>]*>.*?</{re.escape(tag_name)}>",
            "",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        cleaned = re.sub(
            rf"^\s*{re.escape(tag_name)}\s*:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned.strip()

def create_llama_backend(
    model_path: str | Path,
    *,
    n_ctx: int = 2048,
    n_gpu_layers: int = 0,
    verbose: bool = False,
    run_health_check: bool = True,
    model_config: ModelRuntimeConfig | None = None,
) -> InferenceBackend:
    """摘要：工厂方法：可选先轻量 health_check 再构造已加载的 ``LlamaCppBackend``。

    参数：
        model_path: GGUF 路径。
        n_ctx: 推理上下文长度。
        n_gpu_layers: GPU 层数。
        verbose: llama 详细日志。
        run_health_check: 构造前是否执行路径与依赖检查（``load_model=False``，避免重复加载）。

    返回值：
        已加载模型的后端实例。

    异常：
        InferenceBackendError：健康检查未通过。
    """
    if getattr(sys, "frozen", False):
        from offline_companion.runtime.inference_backend.llama_server_backend import (
            LlamaServerBackend,
        )

        backend = LlamaServerBackend(
            model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose,
            model_config=model_config,
        )
        if run_health_check:
            report = backend.health_check()
            if not report.ok:
                raise InferenceBackendError(report.message)
        return backend

    if run_health_check:
        report = LlamaCppBackend.check_model(
            model_path,
            n_ctx=min(n_ctx, 512),
            n_gpu_layers=n_gpu_layers,
            load_model=False,
        )
        if not report.ok:
            raise InferenceBackendError(report.message)
    return LlamaCppBackend(
        model_path,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        verbose=verbose,
        model_config=model_config,
    )


def try_stderr_cuda_hint() -> None:
    """摘要：向 stderr 输出 CUDA 体验提示（不改变控制流）。"""
    print(
        "提示 (Windows / NVIDIA): 建议使用支持 CUDA 的 llama-cpp-python 构建，"
        "并将 --n-gpu-layers 设为大于 0。",
        file=sys.stderr,
    )
