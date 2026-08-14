"""通过独立 llama-server 进程提供本地 GGUF 推理。"""

from __future__ import annotations

import atexit
import ctypes
import datetime as _dt
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from offline_companion.runtime.inference_backend.backend import (
    InferenceHealthReport,
    resolve_gguf_path,
    strip_model_output,
)
from offline_companion.shared.errors import InferenceBackendError
from offline_companion.shared.runtime_paths import data_root
from offline_companion.shared.types import MessageRow, ModelRuntimeConfig


class LlamaServerStartupError(InferenceBackendError):
    """摘要：llama-server 子进程创建或就绪等待失败。"""


def find_llama_server_exe() -> Path:
    """摘要：定位开发环境或 PyInstaller 目录中的 llama-server 可执行文件。

    返回值：
        已解析的可执行文件路径。

    异常：
        InferenceBackendError：所有候选路径均不存在。
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        executable_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                bundle_dir / "llama-server.exe",
                bundle_dir / "llama_server" / "llama-server.exe",
                executable_dir / "llama-server.exe",
                executable_dir / "llama_server" / "llama-server.exe",
                executable_dir / "_internal" / "llama-server.exe",
                executable_dir / "_internal" / "llama_server" / "llama-server.exe",
            ]
        )
    project_root = Path(__file__).resolve().parents[4]
    candidates.append(project_root / "scripts" / "vendor" / "llama-server.exe")

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    searched = "\n".join(f"- {candidate}" for candidate in candidates)
    raise InferenceBackendError(f"未找到 llama-server.exe，已检查：\n{searched}")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class LlamaServerBackend:
    """摘要：管理本机 llama-server 子进程并实现统一推理后端协议。"""

    def __init__(
        self,
        model_path: str | Path,
        *,
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        verbose: bool = False,
        model_config: ModelRuntimeConfig | None = None,
        startup_timeout: float = 30.0,
        request_timeout: float = 180.0,
    ) -> None:
        """摘要：保存服务启动参数，首次健康检查或生成时再启动进程。

        参数：
            model_path: GGUF 模型路径。
            n_ctx: 上下文长度。
            n_gpu_layers: GPU 卸载层数。
            verbose: 是否继承服务端日志输出。
            model_config: 模型运行配置。
            startup_timeout: 模型服务启动超时秒数。
            request_timeout: 单次推理请求超时秒数。
        """
        self.model_path = resolve_gguf_path(model_path)
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self.model_config = model_config or ModelRuntimeConfig(model_id=self.model_path.stem)
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.port = _find_free_port()
        self._base_url = f"http://127.0.0.1:{self.port}"
        self._process: subprocess.Popen[bytes] | None = None
        atexit.register(self.stop)

    def start(self) -> None:
        """摘要：启动 llama-server 并等待模型加载完成。"""
        if self._process is not None and self._process.poll() is None:
            return
        command = [
            str(find_llama_server_exe()),
            "--model",
            str(self.model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--ctx-size",
            str(self.n_ctx),
            "--n-gpu-layers",
            str(self.n_gpu_layers),
        ]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        output = None if self.verbose else subprocess.DEVNULL
        child_env = os.environ.copy()
        child_env.setdefault("PYTHONIOENCODING", "utf-8")
        child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        try:
            restore_dll_directory = None
            if os.name == "nt" and getattr(sys, "frozen", False):
                restore_dll_directory = str(getattr(sys, "_MEIPASS", ""))
                ctypes.windll.kernel32.SetDllDirectoryW(None)
            try:
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=output,
                    creationflags=creation_flags,
                    env=child_env,
                )
            finally:
                if restore_dll_directory:
                    ctypes.windll.kernel32.SetDllDirectoryW(restore_dll_directory)
            self._wait_until_ready()
        except OSError as exc:
            self.stop()
            raise LlamaServerStartupError(f"llama-server 进程启动失败: {exc}") from exc
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        """摘要：终止当前后端持有的 llama-server 子进程。"""
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def health_check(self) -> InferenceHealthReport:
        """摘要：确认服务进程已启动且健康端点可用。"""
        try:
            self.start()
        except (InferenceBackendError, OSError) as exc:
            return InferenceHealthReport(
                ok=False,
                model_path=str(self.model_path),
                message=f"llama-server 启动失败: {exc}",
                backend="llama_server",
            )
        return InferenceHealthReport(
            ok=True,
            model_path=str(self.model_path),
            message=f"模型服务已就绪 (n_ctx={self.n_ctx}, n_gpu_layers={self.n_gpu_layers})",
            backend="llama_server",
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
        """摘要：通过 OpenAI 兼容接口生成一条助手回复。"""
        response: dict[str, Any] | None = None
        for attempt in range(2):
            self.start()
            messages = self._build_messages(
                system_prompt=system_prompt,
                history=history,
                user_message=user_message,
                memory_block=memory_block,
            )
            payload: dict[str, Any] = {
                "model": "local",
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": False,
            }
            if self.model_config.stop_tokens:
                payload["stop"] = list(self.model_config.stop_tokens)
            try:
                response = self._post_json("/v1/chat/completions", payload)
                break
            except InferenceBackendError:
                process = self._process
                if attempt == 0 and process is not None and process.poll() is not None:
                    self._log_sidecar_event(f"llama-server 异常退出，退出码: {process.returncode}")
                    self.stop()
                    continue
                raise
        if response is None:
            raise InferenceBackendError("llama-server 未返回推理响应")
        choices = response.get("choices") or []
        if not choices:
            raise InferenceBackendError(f"推理响应异常: {response!r}")
        content = (choices[0].get("message") or {}).get("content")
        if not content:
            raise InferenceBackendError(f"推理响应无内容: {response!r}")
        return strip_model_output(str(content).strip(), self.model_config)

    def generate_stream(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
        max_tokens: int = 256,
    ) -> Iterator[str]:
        """摘要：通过 llama-server OpenAI 兼容 SSE 接口逐 token 返回文本。"""
        self.start()
        messages = self._build_messages(
            system_prompt=system_prompt,
            history=history,
            user_message=user_message,
            memory_block=memory_block,
        )
        payload: dict[str, Any] = {
            "model": "local",
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if self.model_config.stop_tokens:
            payload["stop"] = list(self.model_config.stop_tokens)
        request = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield str(content)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise InferenceBackendError(f"llama-server stream HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise InferenceBackendError(f"llama-server stream 璇锋眰澶辫触: {exc}") from exc

    def _log_sidecar_event(self, message: str) -> None:
        """摘要：记录 llama-server 子进程生命周期异常。"""
        try:
            log_dir = data_root() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / "llama_server.log").open("a", encoding="utf-8") as handle:
                now = _dt.datetime.now(_dt.timezone.utc)
                handle.write(f"{now.isoformat(timespec='seconds')} {message}\n")
        except OSError:
            return

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                return_code = None if process is None else process.returncode
                raise LlamaServerStartupError(f"llama-server 提前退出，退出码: {return_code}")
            try:
                with urllib.request.urlopen(f"{self._base_url}/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(0.25)
        raise LlamaServerStartupError(f"llama-server 在 {self.startup_timeout:g} 秒内未就绪")

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise InferenceBackendError(f"llama-server HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise InferenceBackendError(f"llama-server 请求失败: {exc}") from exc

    def _build_messages(
        self,
        *,
        system_prompt: str,
        history: list[MessageRow],
        user_message: str,
        memory_block: str,
    ) -> list[dict[str, str]]:
        full_system = system_prompt.rstrip()
        if memory_block.strip():
            full_system = f"{full_system}\n\n{memory_block.strip()}"
        messages: list[dict[str, str]] = []
        if full_system.strip():
            role = "system" if self.model_config.supports_system_role else "user"
            messages.append({"role": role, "content": full_system})
        messages.extend(
            {"role": message.role, "content": message.content}
            for message in history
            if message.role in ("user", "assistant")
        )
        messages.append({"role": "user", "content": user_message})
        return messages


def check_llama_server_model(
    model_path: str | Path,
    *,
    n_ctx: int = 512,
    n_gpu_layers: int = 0,
    probe_generate: bool = False,
) -> InferenceHealthReport:
    """摘要：启动临时 llama-server 实例并验证模型加载和可选生成。"""
    try:
        backend = LlamaServerBackend(
            model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
        )
    except InferenceBackendError as exc:
        return InferenceHealthReport(False, str(model_path), str(exc), "llama_server")
    try:
        report = backend.health_check()
        if report.ok and probe_generate:
            backend.generate(
                system_prompt="",
                history=[],
                user_message="你好",
                memory_block="",
                max_tokens=8,
            )
        return report
    except InferenceBackendError as exc:
        return InferenceHealthReport(False, str(backend.model_path), str(exc), "llama_server")
    finally:
        backend.stop()
