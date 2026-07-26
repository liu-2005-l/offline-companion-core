"""测试：SkillInvoker 进程管理、端口分配、鉴权与 seccomp 引导。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from packaging.version import Version

from offline_companion.shared.errors import (
    CircuitBreakerOpenError,
    SkillInvocationError,
    SkillSourceValidationError,
)
from offline_companion.shell.skill_manager.invoker import (
    _ENTRYPOINT_ENV,
    _SECCOMP_PROFILE_ENV,
    SkillInvoker,
    _env_key_name,
    _find_free_port,
    _generate_api_key,
)
from offline_companion.shell.skill_manager.manifest import SkillEntrypoint, SkillManifest
from offline_companion.shell.skill_manager.seccomp.loader import seccomp_runtime_supported
from offline_companion.shell.skill_manager.seccomp.profiles import (
    SECCOMP_PROFILE_COMPUTE,
    SECCOMP_PROFILE_FILE_IO,
    SECCOMP_PROFILE_NETWORK,
    resolve_runtime_seccomp_profile,
    select_seccomp_profile,
)

pytestmark = pytest.mark.security


def _build_manifest(*, permissions: tuple[str, ...] = (), entrypoint_path: str = "/entry.py") -> SkillManifest:
    """摘要：构造测试用 Skill manifest。"""
    return SkillManifest(
        name="dummy",
        version=Version("1.0.0"),
        version_raw="1.0.0",
        description="测试用 Skill",
        market_id="dummy@1.0.0",
        trust="user_installed",
        entrypoint=SkillEntrypoint(
            type="local_api",
            host="127.0.0.1",
            port=0,
            path=entrypoint_path,
        ),
        permissions=permissions,
        required_api_keys=(),
        output_mode="block",
        raw={},
    )


class TestFindFreePort:
    """测试：动态端口分配。"""

    def test_returns_valid_port(self) -> None:
        port = _find_free_port()
        assert 1024 <= port <= 65535
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))

    def test_returns_different_ports(self) -> None:
        ports = {_find_free_port() for _ in range(5)}
        assert len(ports) > 1


class TestGenerateApiKey:
    """测试：API Key 生成。"""

    def test_key_length(self) -> None:
        key = _generate_api_key()
        assert len(key) == 64
        assert all(ch in "0123456789abcdef" for ch in key)

    def test_key_uniqueness(self) -> None:
        keys = {_generate_api_key() for _ in range(10)}
        assert len(keys) == 10


class TestEnvKeyName:
    """测试：环境变量命名。"""

    def test_basic(self) -> None:
        assert _env_key_name("novel-writer") == "OFFLINE_COMPANION_SKILL_KEY_NOVEL-WRITER"

    def test_uppercase(self) -> None:
        assert _env_key_name("TestSkill") == "OFFLINE_COMPANION_SKILL_KEY_TESTSKILL"


class TestSkillInvoker:
    """测试：SkillInvoker 核心能力。"""

    @pytest.fixture
    def dummy_manifest(self, tmp_path: Path) -> SkillManifest:
        script = tmp_path / "entry.py"
        script.write_text(
            '"""占位入口脚本。"""\n'
            "import json\n"
            "import os\n"
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n\n"
            'API_KEY_NAME = "OFFLINE_COMPANION_SKILL_KEY_DUMMY"\n'
            "assert API_KEY_NAME in os.environ\n"
            'assert "OFFLINE_COMPANION_SKILL_PORT" in os.environ\n'
            'assert "OFFLINE_COMPANION_HOST_PID" in os.environ\n'
            'PORT = int(os.environ["OFFLINE_COMPANION_SKILL_PORT"])\n'
            "API_KEY = os.environ[API_KEY_NAME]\n\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            "    def do_POST(self):\n"
            '        if self.path != "/invoke":\n'
            "            self.send_response(404)\n"
            "            self.end_headers()\n"
            "            return\n"
            '        if self.headers.get("Authorization") != f"Bearer {API_KEY}":\n'
            "            self.send_response(401)\n"
            "            self.end_headers()\n"
            "            return\n"
            '        length = int(self.headers.get("Content-Length", "0"))\n'
            '        body = json.loads(self.rfile.read(length).decode("utf-8"))\n'
            "        self.send_response(200)\n"
            '        self.send_header("Content-Type", "application/json")\n'
            "        self.end_headers()\n"
            '        self.wfile.write(json.dumps({"echo": body}).encode("utf-8"))\n\n'
            'server = HTTPServer(("127.0.0.1", PORT), Handler)\n'
            "while True:\n"
            "    server.handle_request()\n",
            encoding="utf-8",
        )
        return _build_manifest()

    def test_start_and_stop(
        self,
        dummy_manifest: SkillManifest,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invoker = SkillInvoker()
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        process = invoker.start(dummy_manifest, tmp_path)
        assert process.port > 0
        assert len(process.api_key) == 64
        assert process.process.poll() is None
        invoker.stop("dummy")
        assert invoker.get_process("dummy") is None
        process.process.wait(timeout=5)
        assert process.process.poll() is not None

    def test_invoke_real_local_api(
        self,
        dummy_manifest: SkillManifest,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invoker = SkillInvoker()
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        invoker.start(dummy_manifest, tmp_path)
        result = invoker.invoke("dummy", {"value": 1}, "idem-1")
        assert result["echo"]["skill_id"] == "dummy"
        assert result["echo"]["payload"] == {"value": 1}
        assert result["echo"]["idempotency_key"] == "idem-1"
        invoker.stop("dummy")

    def test_invoke_missing_process_raises(self) -> None:
        invoker = SkillInvoker()
        with pytest.raises(SkillInvocationError, match="未运行"):
            invoker.invoke("missing", {})

    def test_start_duplicate_raises(
        self,
        dummy_manifest: SkillManifest,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invoker = SkillInvoker()
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        invoker.start(dummy_manifest, tmp_path)
        with pytest.raises(SkillInvocationError, match="已在运行"):
            invoker.start(dummy_manifest, tmp_path)
        invoker.stop("dummy")

    def test_stop_nonexistent(self) -> None:
        invoker = SkillInvoker()
        invoker.stop("nonexistent")

    def test_stop_all(
        self,
        dummy_manifest: SkillManifest,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invoker = SkillInvoker()
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        process = invoker.start(dummy_manifest, tmp_path)
        invoker.stop_all()
        assert invoker.get_process("dummy") is None
        process.process.wait(timeout=5)
        assert process.process.poll() is not None

    def test_verify_authorization_valid(
        self,
        dummy_manifest: SkillManifest,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invoker = SkillInvoker()
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        process = invoker.start(dummy_manifest, tmp_path)
        assert invoker.verify_authorization("dummy", f"Bearer {process.api_key}")
        invoker.stop("dummy")

    def test_verify_authorization_invalid(
        self,
        dummy_manifest: SkillManifest,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invoker = SkillInvoker()
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        invoker.start(dummy_manifest, tmp_path)
        assert not invoker.verify_authorization("dummy", "Bearer wrong_key")
        assert not invoker.verify_authorization("dummy", None)
        assert not invoker.verify_authorization("dummy", "NotBearer token")
        invoker.stop("dummy")

    def test_verify_authorization_nonexistent(self) -> None:
        invoker = SkillInvoker()
        assert not invoker.verify_authorization("nonexistent", "Bearer key")

    def test_verify_source_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        invoker = SkillInvoker()
        current_pid = os.getpid()
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(current_pid))
        assert invoker.verify_source_pid(current_pid=current_pid)

    def test_verify_source_pid_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        invoker = SkillInvoker()
        monkeypatch.delenv("OFFLINE_COMPANION_HOST_PID", raising=False)
        with pytest.raises(SkillSourceValidationError, match="缺少 OFFLINE_COMPANION_HOST_PID"):
            invoker.verify_source_pid()

    def test_circuit_breaker(
        self,
        dummy_manifest: SkillManifest,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invoker = SkillInvoker()
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        invoker.start(dummy_manifest, tmp_path)
        assert not invoker.is_circuit_open("dummy")
        invoker.record_failure("dummy")
        invoker.record_failure("dummy")
        invoker.record_failure("dummy")
        assert invoker.is_circuit_open("dummy")
        assert not invoker.allow_half_open_probe("dummy")
        invoker._circuit_open["dummy"] = time.time() - invoker.circuit_cooldown_seconds("dummy") - 1
        assert invoker.allow_half_open_probe("dummy")
        assert not invoker.allow_half_open_probe("dummy")
        invoker.record_probe_result("dummy", success=False)
        assert invoker.is_circuit_open("dummy")
        invoker.clear_half_open_probe("dummy")
        invoker._circuit_open["dummy"] = time.time() - invoker.circuit_cooldown_seconds("dummy") - 1
        assert invoker.allow_half_open_probe("dummy")
        invoker.record_probe_result("dummy", success=True)
        assert not invoker.is_circuit_open("dummy")
        invoker.stop("dummy")

    def test_circuit_cooldown_exponential_backoff(self) -> None:
        invoker = SkillInvoker()
        for _ in range(3):
            invoker.record_failure("dummy")
        assert invoker.circuit_cooldown_seconds("dummy") == 300.0
        invoker.record_failure("dummy")
        assert invoker.circuit_cooldown_seconds("dummy") == 600.0
        invoker.record_failure("dummy")
        assert invoker.circuit_cooldown_seconds("dummy") == 1200.0
        for _ in range(20):
            invoker.record_failure("dummy")
        assert invoker.circuit_cooldown_seconds("dummy") == 3600.0

    def test_start_rejected_when_circuit_open(self, dummy_manifest: SkillManifest, tmp_path: Path) -> None:
        invoker = SkillInvoker()
        invoker.record_failure("dummy")
        invoker.record_failure("dummy")
        invoker.record_failure("dummy")
        with pytest.raises(CircuitBreakerOpenError, match="熔断已打开"):
            invoker.start(dummy_manifest, tmp_path)

    def test_start_missing_script(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        invoker = SkillInvoker()
        bad_manifest = _build_manifest(entrypoint_path="/nonexistent.py")
        with pytest.raises(SkillInvocationError, match="入口脚本不存在"):
            invoker.start(bad_manifest, tmp_path)

    def test_unsupported_entrypoint_type(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        invoker = SkillInvoker()
        bad_manifest = SkillManifest(
            name="bad",
            version=Version("1.0.0"),
            version_raw="1.0.0",
            description="测试",
            market_id="bad@1.0.0",
            trust="user_installed",
            entrypoint=SkillEntrypoint(
                type="docker",
                host="127.0.0.1",
                port=0,
                path="/entry.py",
            ),
            permissions=(),
            required_api_keys=(),
            output_mode="block",
            raw={},
        )
        with pytest.raises(SkillInvocationError, match="不支持的 entrypoint 类型"):
            invoker.start(bad_manifest, tmp_path)

    @pytest.mark.parametrize(
        ("permissions", "expected_profile"),
        [
            ((), SECCOMP_PROFILE_NETWORK),
            (("file_access",), SECCOMP_PROFILE_NETWORK),
            (("network_egress",), SECCOMP_PROFILE_NETWORK),
        ],
    )
    def test_start_uses_trusted_bootstrap_and_seccomp_env(
        self,
        permissions: tuple[str, ...],
        expected_profile: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        if seccomp_runtime_supported()[0] and expected_profile != SECCOMP_PROFILE_NETWORK:
            pytest.skip("Linux seccomp 下，local_api 测试脚本需要 network profile 才能启动本地 HTTP 服务")
        script = tmp_path / "entry.py"
        marker = tmp_path / "bootstrap-marker.json"
        script.write_text(
            '"""测试 bootstrap 与 seccomp 环境。"""\n'
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n\n"
            'PORT = int(os.environ["OFFLINE_COMPANION_SKILL_PORT"])\n'
            'marker = Path("bootstrap-marker.json")\n'
            "marker.write_text(json.dumps({\n"
            f'    "entrypoint": os.environ["{_ENTRYPOINT_ENV}"],\n'
            f'    "profile": os.environ["{_SECCOMP_PROFILE_ENV}"],\n'
            '    "status": os.environ["OFFLINE_COMPANION_SKILL_SECCOMP_STATUS"],\n'
            '    "reason": os.environ.get("OFFLINE_COMPANION_SKILL_SECCOMP_REASON", ""),\n'
            "}, ensure_ascii=False), encoding='utf-8')\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            "    def do_POST(self):\n"
            "        self.send_response(200)\n"
            "        self.end_headers()\n"
            'server = HTTPServer(("127.0.0.1", PORT), Handler)\n'
            "while True:\n"
            "    server.handle_request()\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("OFFLINE_COMPANION_HOST_PID", str(os.getpid()))
        invoker = SkillInvoker()
        invoker.start(_build_manifest(permissions=permissions), tmp_path)
        try:
            deadline = time.time() + 5
            while time.time() < deadline and not marker.exists():
                time.sleep(0.05)
            assert marker.exists()
            payload = json.loads(marker.read_text(encoding="utf-8"))
        finally:
            invoker.stop("dummy")
        assert payload["entrypoint"] == str(script.resolve())
        assert payload["profile"] == expected_profile
        supported, _ = seccomp_runtime_supported()
        assert payload["status"] == ("applied" if supported else "skipped")


@pytest.mark.parametrize(
    ("permissions", "expected_profile"),
    [
        ((), SECCOMP_PROFILE_COMPUTE),
        (("file_access",), SECCOMP_PROFILE_FILE_IO),
        (("network_egress",), SECCOMP_PROFILE_NETWORK),
        (("cloud_inference",), SECCOMP_PROFILE_NETWORK),
        (("file_access", "network_egress"), SECCOMP_PROFILE_NETWORK),
    ],
)
def test_select_seccomp_profile_prefers_minimum_permissions(
    permissions: tuple[str, ...],
    expected_profile: str,
) -> None:
    manifest = _build_manifest(permissions=permissions)
    assert select_seccomp_profile(manifest) == expected_profile


def test_resolve_runtime_seccomp_profile_elevates_local_api() -> None:
    manifest = _build_manifest()
    assert resolve_runtime_seccomp_profile(manifest) == SECCOMP_PROFILE_NETWORK


def test_seccomp_runtime_supported_non_linux_degrades() -> None:
    supported, reason = seccomp_runtime_supported(system_name="Windows", machine_name="AMD64")
    assert not supported
    assert "Linux" in reason


@pytest.mark.security
@pytest.mark.linux_seccomp
@pytest.mark.skipif(not seccomp_runtime_supported()[0], reason="仅在 Linux seccomp 环境执行")
def test_linux_seccomp_compute_profile_blocks_socket() -> None:
    result = _run_seccomp_probe(
        profile=SECCOMP_PROFILE_COMPUTE,
        operation_code="""
import socket
try:
    socket.socket(socket.AF_INET, socket.SOCK_STREAM)
except OSError as exc:
    outcome = {"blocked": True, "errno": getattr(exc, "errno", None), "type": exc.__class__.__name__}
else:
    outcome = {"blocked": False}
""",
    )
    assert result["applied"] is True
    assert result["blocked"] is True
    assert result["errno"] == 1


@pytest.mark.security
@pytest.mark.linux_seccomp
@pytest.mark.skipif(not seccomp_runtime_supported()[0], reason="仅在 Linux seccomp 环境执行")
def test_linux_seccomp_compute_profile_allows_file_read(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("ok", encoding="utf-8")
    result = _run_seccomp_probe(
        profile=SECCOMP_PROFILE_COMPUTE,
        operation_code=f"""
from pathlib import Path
content = Path({str(sample)!r}).read_text(encoding="utf-8")
outcome = {{"content": content}}
""",
    )
    assert result["applied"] is True
    assert result["content"] == "ok"


@pytest.mark.security
@pytest.mark.linux_seccomp
@pytest.mark.skipif(not seccomp_runtime_supported()[0], reason="仅在 Linux seccomp 环境执行")
def test_linux_seccomp_compute_profile_blocks_execve() -> None:
    result = _run_seccomp_probe(
        profile=SECCOMP_PROFILE_COMPUTE,
        operation_code="""
import subprocess
import sys
try:
    subprocess.run([sys.executable, "-c", "print('child')"], check=True)
except OSError as exc:
    outcome = {"blocked": True, "errno": getattr(exc, "errno", None), "type": exc.__class__.__name__}
else:
    outcome = {"blocked": False}
""",
    )
    assert result["applied"] is True
    assert result["blocked"] is True
    assert result["errno"] == 1


def _run_seccomp_probe(*, profile: str, operation_code: str) -> dict[str, object]:
    """摘要：在独立 Python 子进程中装载 seccomp 并执行探针代码。"""
    script = "\n".join(
        [
            "import json",
            "from offline_companion.shell.skill_manager.seccomp.loader import load_profile",
            "",
            f"load_result = load_profile({profile!r})",
            'outcome = {"applied": load_result.applied, "profile": load_result.profile}',
            textwrap.dedent(operation_code).strip(),
            "print(json.dumps(outcome, ensure_ascii=False))",
        ]
    )
    env = dict(os.environ)
    env.pop("OFFLINE_COMPANION_DISABLE_SECCOMP", None)
    pythonpath = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = "src" if not pythonpath else os.pathsep.join(("src", pythonpath))
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    return json.loads(completed.stdout.strip())
