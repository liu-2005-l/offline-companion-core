"""invoker：Skill 进程管理、动态端口分配、API Key 注入与鉴权（A2；不发起网络）。"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from offline_companion.shared.errors import (
    CircuitBreakerOpenError,
    SkillInvocationError,
    SkillSourceValidationError,
)

if TYPE_CHECKING:
    from .manifest import SkillManifest

# 环境变量前缀：宿主注入 Skill API Key 时使用
_ENV_KEY_PREFIX = "OFFLINE_COMPANION_SKILL_KEY_"


def _find_free_port() -> int:
    """摘要：在 127.0.0.1 上分配一个临时空闲端口（禁用固定端口）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _generate_api_key() -> str:
    """摘要：生成 32 字节随机 API Key（hex 编码，64 字符）。"""
    return secrets.token_hex(32)


def _env_key_name(skill_name: str) -> str:
    """摘要：构造环境变量名 ``OFFLINE_COMPANION_SKILL_KEY_<NAME>``。"""
    return f"{_ENV_KEY_PREFIX}{skill_name.upper()}"


@dataclass
class SkillProcess:
    """摘要：已启动的 Skill 子进程信息。

    参数：
        manifest: 对应的 SkillManifest。
        port: 动态分配的本地端口。
        api_key: 一次性随机 API Key。
        process: subprocess.Popen 句柄。
    """

    manifest: SkillManifest
    port: int
    api_key: str
    process: subprocess.Popen


@dataclass
class SkillInvoker:
    """摘要：Skill 进程生命周期管理器（A2 层；单进程模型）。

    说明：
        - 启动时分配动态端口，生成随机 API Key，通过环境变量注入。
        - 调用时校验 ``Authorization`` 请求头。
        - 来源校验：仅接受主进程 PID 的连接（通过环境变量传递）。
        - 熔断接口占位（Sprint 7.9 完善）。
    """

    _processes: dict[str, SkillProcess] = field(default_factory=dict)

    # --- 熔断占位（Sprint 7.9 完善） ---
    _failure_counts: dict[str, int] = field(default_factory=dict)
    _circuit_open: dict[str, bool] = field(default_factory=dict)
    _half_open_probe: dict[str, bool] = field(default_factory=dict)
    # TODO(sprint7-close): 熔断策略当前仅有最小闭环，后续应补半开探测、恢复窗口与指数退避。

    def start(self, manifest: SkillManifest, install_dir: Path) -> SkillProcess:
        """摘要：启动 Skill 子进程。

        参数：
            manifest: 已通过 policy 校验的 SkillManifest。
            install_dir: Skill 安装目录（``extensions/installed/<name>/``）。

        返回：
            SkillProcess：包含动态端口、API Key、进程句柄。

        异常：
            SkillInvocationError：启动失败或端口分配失败。
        """
        name = manifest.name
        if name in self._processes:
            raise SkillInvocationError(f"Skill {name!r} 已在运行")
        if self.is_circuit_open(name):
            raise CircuitBreakerOpenError(f"Skill {name!r} 熔断已打开")

        port = _find_free_port()
        api_key = _generate_api_key()

        # 构造启动命令：由 manifest entrypoint 决定
        entry = manifest.entrypoint
        if entry.type != "local_api":
            raise SkillInvocationError(
                f"不支持的 entrypoint 类型 {entry.type!r}（仅支持 local_api）"
            )

        # 构造子进程环境变量
        env = dict(os.environ)
        env[_env_key_name(name)] = api_key
        env["OFFLINE_COMPANION_SKILL_PORT"] = str(port)
        env["OFFLINE_COMPANION_HOST_PID"] = str(os.getpid())

        # 启动命令：假设 Skill 目录下有可执行入口
        # MVP 阶段支持两种模式：
        #   1. entrypoint.path 指向 Python 脚本
        #   2. 通过 sys.executable 运行
        script_path = install_dir / entry.path.lstrip("/")
        if not script_path.is_file():
            raise SkillInvocationError(
                f"Skill 入口脚本不存在: {script_path}"
            )

        try:
            proc = subprocess.Popen(
                [sys.executable, str(script_path)],
                cwd=str(install_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            raise SkillInvocationError(
                f"启动 Skill {name!r} 失败: {e}"
            ) from e

        if not self.verify_source_pid():
            proc.terminate()
            raise SkillInvocationError(f"Skill {name!r} 来源校验失败")

        sp = SkillProcess(
            manifest=manifest,
            port=port,
            api_key=api_key,
            process=proc,
        )
        self._processes[name] = sp
        return sp

    def stop(self, name: str) -> None:
        """摘要：停止指定 Skill 子进程。"""
        sp = self._processes.pop(name, None)
        if sp is None:
            return
        sp.process.terminate()
        try:
            sp.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sp.process.kill()
            sp.process.wait(timeout=5)

    def stop_all(self) -> None:
        """摘要：停止所有 Skill 子进程。"""
        for name in list(self._processes.keys()):
            self.stop(name)

    def get_process(self, name: str) -> SkillProcess | None:
        """摘要：获取已启动的 Skill 进程信息。"""
        return self._processes.get(name)

    def verify_authorization(self, name: str, auth_header: str | None) -> bool:
        """摘要：校验 ``Authorization`` 请求头是否匹配 Skill API Key。

        参数：
            name: Skill 名称。
            auth_header: HTTP ``Authorization`` 请求头值。

        返回：
            True 表示鉴权通过。
        """
        sp = self._processes.get(name)
        if sp is None:
            return False
        if auth_header is None:
            return False
        # 期望格式：Bearer <api_key>
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[len("Bearer "):]
        return secrets.compare_digest(token, sp.api_key)

    def verify_source_pid(self, *, current_pid: int | None = None) -> bool:
        """摘要：来源校验 — 仅接受主进程 PID 的连接。

        参数：
            current_pid: 可注入的当前进程 PID，便于测试与宿主侧自检。

        返回：
            True 表示当前进程来源与宿主 PID 一致。

        Raises:
            SkillSourceValidationError: 宿主 PID 缺失或不匹配。
        """
        host_pid_raw = os.environ.get("OFFLINE_COMPANION_HOST_PID", "").strip()
        if not host_pid_raw:
            raise SkillSourceValidationError("缺少 OFFLINE_COMPANION_HOST_PID")
        try:
            host_pid = int(host_pid_raw)
        except ValueError as e:
            raise SkillSourceValidationError(
                f"OFFLINE_COMPANION_HOST_PID 非法: {host_pid_raw!r}"
            ) from e
        pid = os.getpid() if current_pid is None else int(current_pid)
        if host_pid != pid:
            raise SkillSourceValidationError(
                f"来源 PID 不匹配：host={host_pid} current={pid}"
            )
        return True

    # --- 熔断占位（Sprint 7.9 完善） ---

    def record_failure(self, name: str) -> None:
        """摘要：记录一次调用失败（熔断计数器）。"""
        self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
        if self._failure_counts[name] >= 3:
            self._circuit_open[name] = True
            self._half_open_probe.pop(name, None)

    def ensure_circuit_closed(self, name: str) -> None:
        """摘要：在调用前检查熔断状态。

        Raises:
            CircuitBreakerOpenError: 目标 Skill 已进入熔断状态且不允许半开探测。
        """
        if self.is_circuit_open(name) and not self.allow_half_open_probe(name):
            raise CircuitBreakerOpenError(f"Skill {name!r} 熔断已打开")

    def allow_half_open_probe(self, name: str) -> bool:
        """摘要：熔断后允许一次半开探测。

        返回：
            True 表示允许发起一次探测；False 表示已探测过或未处于熔断态。
        """
        return self.should_probe_half_open(name)

    def record_probe_result(self, name: str, success: bool) -> None:
        """摘要：记录半开探测结果。"""
        if success:
            self.record_success(name)
        else:
            self.record_failure(name)
            self._circuit_open[name] = True

    def record_success(self, name: str) -> None:
        """摘要：记录一次调用成功（重置熔断计数器）。"""
        self._failure_counts.pop(name, None)
        self._circuit_open.pop(name, None)
        self._half_open_probe.pop(name, None)

    def is_circuit_open(self, name: str) -> bool:
        """摘要：检查熔断是否已打开。"""
        return self._circuit_open.get(name, False)

    def should_probe_half_open(self, name: str) -> bool:
        """摘要：半开状态下是否允许一次探测。"""
        if not self.is_circuit_open(name):
            return False
        if self._half_open_probe.get(name, False):
            return False
        self._half_open_probe[name] = True
        return True

    def clear_half_open_probe(self, name: str) -> None:
        """摘要：清除半开探测占位，供恢复或失败后重试。"""
        self._half_open_probe.pop(name, None)
