"""invoker：Skill 进程管理、鉴权与受信引导。"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from offline_companion.shared.errors import (
    CircuitBreakerOpenError,
    SkillBuiltinHashMismatchError,
    SkillHashMissingError,
    SkillInvocationError,
    SkillSourceValidationError,
    SkillTrustAnchorMissingError,
)
from offline_companion.shell.skill_manager.seccomp.profiles import resolve_runtime_seccomp_profile
from offline_companion.shell.skill_manager.supply_chain import (
    audit_supply_chain_failure,
    verify_supply_chain,
)

if TYPE_CHECKING:
    from .manifest import SkillManifest

_ENV_KEY_PREFIX = "OFFLINE_COMPANION_SKILL_KEY_"
_ENTRYPOINT_ENV = "OFFLINE_COMPANION_SKILL_ENTRYPOINT"
_SECCOMP_PROFILE_ENV = "OFFLINE_COMPANION_SKILL_SECCOMP_PROFILE"
_RUNTIME_NETWORK_ALLOWED_ENV = "OFFLINE_COMPANION_SKILL_NETWORK_ALLOWED"
_CHILD_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TMP",
    "TEMP",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
)

logger = logging.getLogger(__name__)


def _find_free_port() -> int:
    """摘要：在 ``127.0.0.1`` 上分配一个临时空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _generate_api_key() -> str:
    """摘要：生成一次性随机 API Key。"""
    return secrets.token_hex(32)


def _env_key_name(skill_name: str) -> str:
    """摘要：返回宿主注入给 Skill 的 API Key 环境变量名。"""
    return f"{_ENV_KEY_PREFIX}{skill_name.upper()}"


def _manifest_allows_network(manifest: SkillManifest) -> bool:
    """摘要：判断 Skill manifest 是否声明了网络或云端权限。"""
    permissions = set(getattr(manifest, "permissions", ()) or ())
    return bool(permissions.intersection({"network_egress", "cloud_inference"}))


@dataclass
class SkillProcess:
    """摘要：描述已启动的 Skill 子进程。

    参数：
        manifest: 对应的 Skill manifest。
        port: 动态分配的本地端口。
        api_key: 注入给 Skill 的一次性 API Key。
        process: 子进程句柄。
    """

    manifest: SkillManifest
    port: int
    api_key: str
    process: subprocess.Popen


@dataclass
class SkillInvoker:
    """摘要：负责 Skill 生命周期管理与本地调用。

    说明：
        - 启动前先做来源校验与供应链校验。
        - 启动时通过受信 bootstrap 注入端口、API Key 和 seccomp profile。
        - 默认仅向子进程透传最小必需环境变量，避免宿主敏感配置泄漏。
    """

    _processes: dict[str, SkillProcess] = field(default_factory=dict)
    _failure_counts: dict[str, int] = field(default_factory=dict)
    _circuit_open: dict[str, float] = field(default_factory=dict)
    _half_open_probe: dict[str, bool] = field(default_factory=dict)
    api_key_resolver: Callable[[str], str | None] | None = None
    _circuit_cooldown_s: float = 300.0
    _circuit_cooldown_max_s: float = 3600.0

    def start(self, manifest: SkillManifest, install_dir: Path) -> SkillProcess:
        """摘要：启动一个 Skill 子进程。

        参数：
            manifest: 已通过 policy 校验的 Skill manifest。
            install_dir: Skill 安装目录。

        返回：
            SkillProcess：启动后的进程信息。

        Raises:
            SkillInvocationError: 启动失败或入口不合法。
            CircuitBreakerOpenError: 对应 Skill 已处于熔断状态。
        """
        name = manifest.name
        if name in self._processes:
            raise SkillInvocationError(f"Skill {name!r} 已在运行")
        if self.is_circuit_open(name):
            raise CircuitBreakerOpenError(f"Skill {name!r} 熔断已打开")

        self.verify_source_pid()
        try:
            verify_supply_chain(manifest, install_dir)
        except (
            SkillHashMissingError,
            SkillBuiltinHashMismatchError,
            SkillTrustAnchorMissingError,
        ) as exc:
            audit = audit_supply_chain_failure(exc, skill_name=manifest.name)
            logger.error("supply_chain_validation_failed", extra=audit)
            raise

        entry = manifest.entrypoint
        if entry.type != "local_api":
            raise SkillInvocationError(f"不支持的 entrypoint 类型 {entry.type!r}（仅支持 local_api）")

        port = self._allocate_port_with_retry()
        api_key = _generate_api_key()
        script_path = (install_dir / entry.path.lstrip("/")).resolve()
        install_root = install_dir.resolve()
        if not self._is_within_directory(script_path, install_root):
            raise SkillInvocationError("入口路径越界")
        if not script_path.is_file():
            raise SkillInvocationError(f"Skill 入口脚本不存在: {script_path}")

        env = self._build_child_env()
        env[_env_key_name(name)] = api_key
        env["OFFLINE_COMPANION_SKILL_PORT"] = str(port)
        env["OFFLINE_COMPANION_HOST_PID"] = str(os.getpid())
        env[_ENTRYPOINT_ENV] = str(script_path)
        env[_SECCOMP_PROFILE_ENV] = resolve_runtime_seccomp_profile(manifest)
        env[_RUNTIME_NETWORK_ALLOWED_ENV] = "1" if _manifest_allows_network(manifest) else "0"
        self._inject_required_api_keys(env, manifest)
        self._prepend_pythonpath(env, self._trusted_src_root())

        try:
            proc = subprocess.Popen(
                self._build_launch_command(),
                cwd=str(install_dir),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise SkillInvocationError(f"启动 Skill {name!r} 失败: {exc}") from exc

        try:
            self._wait_ready(proc, port, timeout=5.0)
        except Exception:
            proc.terminate()
            raise

        skill_process = SkillProcess(
            manifest=manifest,
            port=port,
            api_key=api_key,
            process=proc,
        )
        self._processes[name] = skill_process
        return skill_process

    def _build_launch_command(self) -> list[str]:
        """摘要：返回受信 bootstrap 启动命令。"""
        return [
            sys.executable,
            "-m",
            "offline_companion.shell.skill_manager.seccomp.trusted_skill_bootstrap",
        ]

    def _trusted_src_root(self) -> Path:
        """摘要：返回宿主受信代码的 ``src`` 根目录。"""
        return Path(__file__).resolve().parents[3]

    def _prepend_pythonpath(self, env: dict[str, str], path: Path) -> None:
        """摘要：将受信 ``src`` 根目录加入子进程 ``PYTHONPATH``。"""
        current = env.get("PYTHONPATH", "").strip()
        prefix = str(path)
        env["PYTHONPATH"] = prefix if not current else os.pathsep.join((prefix, current))

    def _build_child_env(self) -> dict[str, str]:
        """摘要：仅向 Skill 子进程传递最小必需环境变量。"""
        env: dict[str, str] = {}
        for key in _CHILD_ENV_ALLOWLIST:
            value = os.environ.get(key)
            if value:
                env[key] = value
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def _inject_required_api_keys(self, env: dict[str, str], manifest: SkillManifest) -> None:
        """摘要：按 manifest.required_api_keys 由宿主解析并注入 API key。"""
        for key_name in manifest.required_api_keys:
            normalized = str(key_name or "").strip()
            if not normalized:
                continue
            value = self._resolve_api_key(normalized)
            if not value:
                raise SkillInvocationError(f"Skill {manifest.name!r} 缺少必需 API key: {normalized}")
            env[normalized] = value

    def _resolve_api_key(self, key_name: str) -> str | None:
        """摘要：解析宿主可用的 API key，优先使用显式 resolver，再回退环境变量。"""
        if self.api_key_resolver is not None:
            value = self.api_key_resolver(key_name)
            if value:
                return str(value)
        return os.environ.get(key_name) or os.environ.get(key_name.upper())

    def _allocate_port_with_retry(self, retries: int = 5) -> int:
        """摘要：分配不与已启动 Skill 冲突的本地端口。"""
        last_error: Exception | None = None
        for _ in range(max(1, retries)):
            port = _find_free_port()
            if port not in {process.port for process in self._processes.values()}:
                return port
            last_error = SkillInvocationError(f"端口 {port} 已被占用")
            time.sleep(0.05)
        if last_error is not None:
            raise last_error
        raise SkillInvocationError("无法分配空闲端口")

    def _wait_ready(self, proc: subprocess.Popen, port: int, timeout: float = 5.0) -> None:
        """摘要：等待 Skill 本地服务就绪。

        说明：
            bootstrap 若提前崩溃，应立即返回错误而不是空等超时。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                stderr_output = self._read_process_stderr(proc)
                message = f"bootstrap 进程已退出，code={proc.returncode}"
                if stderr_output:
                    message = f"{message}: {stderr_output}"
                raise SkillInvocationError(message)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise SkillInvocationError("Skill 启动超时")

    def _read_process_stderr(self, proc: subprocess.Popen) -> str:
        """摘要：安全读取子进程 stderr，便于启动失败时排障。"""
        if proc.stderr is None:
            return ""
        try:
            return proc.stderr.read().decode("utf-8", errors="replace").strip()
        except (AttributeError, OSError, ValueError):
            return ""

    def _is_within_directory(self, path: Path, directory: Path) -> bool:
        """摘要：判断路径是否位于指定目录树内。"""
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False

    def stop(self, name: str) -> None:
        """摘要：停止指定 Skill 进程。"""
        skill_process = self._processes.pop(name, None)
        if skill_process is None:
            return
        skill_process.process.terminate()
        try:
            skill_process.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            skill_process.process.kill()
            skill_process.process.wait(timeout=5)

    def stop_all(self) -> None:
        """摘要：停止全部 Skill 进程。"""
        for name in list(self._processes.keys()):
            self.stop(name)

    def invoke(self, name: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Any:
        """摘要：通过本地 HTTP 接口调用已启动的 Skill。"""
        skill_process = self._processes.get(name)
        if skill_process is None:
            raise SkillInvocationError(f"Skill {name!r} 未运行")
        self.ensure_circuit_closed(name)
        if skill_process.process.poll() is not None:
            self.record_failure(name)
            raise SkillInvocationError(f"Skill {name!r} 进程已退出")

        request_body = json.dumps(
            {
                "skill_id": name,
                "payload": payload,
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{skill_process.port}/invoke",
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {skill_process.api_key}",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=30) as response:
                content_type = response.headers.get_content_type()
                raw = response.read()
        except HTTPError as exc:
            self.record_failure(name)
            raise SkillInvocationError(f"Skill {name!r} 调用失败: HTTP {exc.code}") from exc
        except URLError as exc:
            self.record_failure(name)
            raise SkillInvocationError(f"Skill {name!r} 调用失败: {exc.reason}") from exc
        except Exception as exc:
            self.record_failure(name)
            raise SkillInvocationError(f"Skill {name!r} 调用失败: {exc}") from exc

        try:
            if content_type == "application/json":
                result = json.loads(raw.decode("utf-8"))
            else:
                text = raw.decode("utf-8")
                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    result = {"result": text}
        except Exception as exc:
            self.record_failure(name)
            raise SkillInvocationError(f"Skill {name!r} 响应解析失败: {exc}") from exc

        self.record_success(name)
        return result

    def get_process(self, name: str) -> SkillProcess | None:
        """摘要：返回已启动 Skill 的进程信息。"""
        return self._processes.get(name)

    def is_alive(self, name: str) -> bool:
        """??????? Skill ?????????"""
        skill_process = self.get_process(name)
        return skill_process is not None and skill_process.process.poll() is None

    def verify_authorization(self, name: str, auth_header: str | None) -> bool:
        """摘要：校验 ``Authorization`` 请求头是否与 Skill API Key 匹配。"""
        skill_process = self._processes.get(name)
        if skill_process is None or auth_header is None:
            return False
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[len("Bearer ") :]
        return secrets.compare_digest(token, skill_process.api_key)

    def verify_source_pid(self, *, current_pid: int | None = None) -> bool:
        """摘要：校验当前进程是否由宿主 PID 发起。

        参数：
            current_pid: 便于测试时注入的当前进程 PID。

        返回：
            bool：校验通过时返回 ``True``。

        Raises:
            SkillSourceValidationError: 宿主 PID 缺失、非法或与当前 PID 不一致。
        """
        host_pid_raw = os.environ.get("OFFLINE_COMPANION_HOST_PID", "").strip()
        if not host_pid_raw:
            raise SkillSourceValidationError("缺少 OFFLINE_COMPANION_HOST_PID")
        try:
            host_pid = int(host_pid_raw)
        except ValueError as exc:
            raise SkillSourceValidationError(f"OFFLINE_COMPANION_HOST_PID 非法: {host_pid_raw!r}") from exc
        pid = os.getpid() if current_pid is None else int(current_pid)
        if host_pid != pid:
            raise SkillSourceValidationError(f"来源 PID 不匹配：host={host_pid} current={pid}")
        return True

    def record_failure(self, name: str) -> None:
        """摘要：记录一次调用失败并更新熔断状态。"""
        self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
        if self._failure_counts[name] >= 3:
            self._circuit_open[name] = time.time()
            self._half_open_probe.pop(name, None)

    def circuit_cooldown_seconds(self, name: str) -> float:
        """摘要：按连续失败次数计算指数退避冷却时间。"""
        fail_count = max(3, self._failure_counts.get(name, 3))
        cooldown = self._circuit_cooldown_s * (2 ** (fail_count - 3))
        return min(float(cooldown), self._circuit_cooldown_max_s)

    def ensure_circuit_closed(self, name: str) -> None:
        """摘要：在调用前检查熔断状态。"""
        if self.is_circuit_open(name) and not self.allow_half_open_probe(name):
            raise CircuitBreakerOpenError(f"Skill {name!r} 熔断已打开")

    def allow_half_open_probe(self, name: str) -> bool:
        """摘要：在熔断冷却后允许一次半开探测。"""
        return self.should_probe_half_open(name)

    def record_probe_result(self, name: str, success: bool) -> None:
        """摘要：记录半开探测结果。"""
        if success:
            self.record_success(name)
            return
        self.record_failure(name)
        self._circuit_open[name] = time.time()

    def record_success(self, name: str) -> None:
        """摘要：记录一次成功调用并重置熔断状态。"""
        self._failure_counts.pop(name, None)
        self._circuit_open.pop(name, None)
        self._half_open_probe.pop(name, None)

    def is_circuit_open(self, name: str) -> bool:
        """摘要：返回当前 Skill 是否处于熔断状态。"""
        return bool(self._circuit_open.get(name))

    def should_probe_half_open(self, name: str) -> bool:
        """摘要：判断是否允许执行一次半开探测。"""
        opened_at = self._circuit_open.get(name)
        if opened_at is None:
            return False
        if time.time() - opened_at < self.circuit_cooldown_seconds(name):
            return False
        if self._half_open_probe.get(name, False):
            return False
        self._half_open_probe[name] = True
        return True

    def clear_half_open_probe(self, name: str) -> None:
        """摘要：清理半开探测占位。"""
        self._half_open_probe.pop(name, None)
