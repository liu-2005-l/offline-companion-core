"""mock：无 GPU 的确定性推理后端（测试/开发）。"""

from __future__ import annotations

from dataclasses import dataclass

from offline_companion.runtime.inference_backend.backend import InferenceHealthReport
from offline_companion.shared.types import MessageRow


@dataclass
class EchoBackend:
    """摘要：回显式后端，用于 CI 或无 GGUF 环境。"""

    label: str = "echo"

    def health_check(self) -> InferenceHealthReport:
        """摘要：Echo 后端始终视为可用（不加载 GGUF）。"""
        return InferenceHealthReport(
            ok=True,
            model_path="",
            message=f"Echo 后端 ({self.label})",
            backend="echo",
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
        mem = f"\n\n[memory]\n{memory_block}" if memory_block.strip() else ""
        return f"[{self.label}] {user_message}{mem}"
