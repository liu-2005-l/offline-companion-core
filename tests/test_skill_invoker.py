"""测试：SkillInvoker 进程管理、动态端口、API Key 注入与鉴权。"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from packaging.version import Version

from offline_companion.shared.errors import SkillInvocationError
from offline_companion.shell.skill_manager.invoker import (
    SkillInvoker,
    _env_key_name,
    _find_free_port,
    _generate_api_key,
)
from offline_companion.shell.skill_manager.manifest import SkillEntrypoint, SkillManifest


class TestFindFreePort:
    """测试：动态端口分配。"""

    def test_returns_valid_port(self) -> None:
        """返回的端口应在有效范围内且可绑定。"""
        port = _find_free_port()
        assert 1024 <= port <= 65535
        # 验证端口确实可用
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))

    def test_returns_different_ports(self) -> None:
        """连续调用应返回不同端口。"""
        ports = {_find_free_port() for _ in range(5)}
        assert len(ports) > 1


class TestGenerateApiKey:
    """测试：API Key 生成。"""

    def test_key_length(self) -> None:
        """Key 应为 64 字符 hex 字符串。"""
        key = _generate_api_key()
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_key_uniqueness(self) -> None:
        """连续生成应不重复。"""
        keys = {_generate_api_key() for _ in range(10)}
        assert len(keys) == 10


class TestEnvKeyName:
    """测试：环境变量名构造。"""

    def test_basic(self) -> None:
        assert _env_key_name("novel-writer") == "OFFLINE_COMPANION_SKILL_KEY_NOVEL-WRITER"

    def test_uppercase(self) -> None:
        assert _env_key_name("TestSkill") == "OFFLINE_COMPANION_SKILL_KEY_TESTSKILL"


class TestSkillInvoker:
    """测试：SkillInvoker 核心功能。"""

    @pytest.fixture
    def dummy_manifest(self, tmp_path: Path) -> SkillManifest:
        """创建一个虚拟 manifest，entrypoint 指向临时脚本。"""
        script = tmp_path / "entry.py"
        script.write_text(
            '"""占位入口脚本。"""\nimport time\nimport os\n\n'
            "# 验证环境变量已注入\n"
            'assert "OFFLINE_COMPANION_SKILL_KEY_DUMMY" in os.environ\n'
            'assert "OFFLINE_COMPANION_SKILL_PORT" in os.environ\n'
            'assert "OFFLINE_COMPANION_HOST_PID" in os.environ\n'
            "# 保持运行直到被终止\n"
            "while True:\n"
            "    time.sleep(1)\n",
            encoding="utf-8",
        )

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
                path="/entry.py",
            ),
            permissions=(),
            required_api_keys=(),
            output_mode="block",
            raw={},
        )

    def test_start_and_stop(self, dummy_manifest: SkillManifest, tmp_path: Path) -> None:
        """启动后应分配端口和 Key；停止后进程应退出。"""
        invoker = SkillInvoker()
        sp = invoker.start(dummy_manifest, tmp_path)
        assert sp.port > 0
        assert len(sp.api_key) == 64
        assert sp.process.poll() is None  # 进程应运行中

        invoker.stop("dummy")
        assert invoker.get_process("dummy") is None
        sp.process.wait(timeout=5)
        assert sp.process.poll() is not None

    def test_start_duplicate_raises(
        self, dummy_manifest: SkillManifest, tmp_path: Path
    ) -> None:
        """重复启动同一 Skill 应抛出异常。"""
        invoker = SkillInvoker()
        invoker.start(dummy_manifest, tmp_path)
        with pytest.raises(SkillInvocationError, match="已在运行"):
            invoker.start(dummy_manifest, tmp_path)
        invoker.stop("dummy")

    def test_stop_nonexistent(self) -> None:
        """停止不存在的 Skill 不应抛出异常。"""
        invoker = SkillInvoker()
        invoker.stop("nonexistent")  # 不应抛出

    def test_stop_all(self, dummy_manifest: SkillManifest, tmp_path: Path) -> None:
        """stop_all 应停止所有进程。"""
        invoker = SkillInvoker()
        sp1 = invoker.start(dummy_manifest, tmp_path)
        invoker.stop_all()
        assert invoker.get_process("dummy") is None
        sp1.process.wait(timeout=5)
        assert sp1.process.poll() is not None

    def test_verify_authorization_valid(
        self, dummy_manifest: SkillManifest, tmp_path: Path
    ) -> None:
        """正确的 Bearer token 应通过鉴权。"""
        invoker = SkillInvoker()
        sp = invoker.start(dummy_manifest, tmp_path)
        assert invoker.verify_authorization("dummy", f"Bearer {sp.api_key}")
        invoker.stop("dummy")

    def test_verify_authorization_invalid(
        self, dummy_manifest: SkillManifest, tmp_path: Path
    ) -> None:
        """错误的 token 应拒绝。"""
        invoker = SkillInvoker()
        invoker.start(dummy_manifest, tmp_path)
        assert not invoker.verify_authorization("dummy", "Bearer wrong_key")
        assert not invoker.verify_authorization("dummy", None)
        assert not invoker.verify_authorization("dummy", "NotBearer token")
        invoker.stop("dummy")

    def test_verify_authorization_nonexistent(self) -> None:
        """不存在的 Skill 应拒绝。"""
        invoker = SkillInvoker()
        assert not invoker.verify_authorization("nonexistent", "Bearer key")

    def test_verify_source_pid(self) -> None:
        """来源校验占位实现应恒返回 True。"""
        invoker = SkillInvoker()
        assert invoker.verify_source_pid()

    def test_circuit_breaker(self, dummy_manifest: SkillManifest, tmp_path: Path) -> None:
        """熔断计数器应在连续失败后打开。"""
        invoker = SkillInvoker()
        invoker.start(dummy_manifest, tmp_path)

        assert not invoker.is_circuit_open("dummy")
        invoker.record_failure("dummy")
        invoker.record_failure("dummy")
        invoker.record_failure("dummy")
        assert invoker.is_circuit_open("dummy")

        invoker.record_success("dummy")
        assert not invoker.is_circuit_open("dummy")

        invoker.stop("dummy")

    def test_start_missing_script(self, dummy_manifest: SkillManifest, tmp_path: Path) -> None:
        """入口脚本不存在时应抛出异常。"""
        invoker = SkillInvoker()
        # 修改 entrypoint 指向不存在的文件
        bad_manifest = SkillManifest(
            name="bad",
            version=Version("1.0.0"),
            version_raw="1.0.0",
            description="测试",
            market_id="bad@1.0.0",
            trust="user_installed",
            entrypoint=SkillEntrypoint(
                type="local_api",
                host="127.0.0.1",
                port=0,
                path="/nonexistent.py",
            ),
            permissions=(),
            required_api_keys=(),
            output_mode="block",
            raw={},
        )
        with pytest.raises(SkillInvocationError, match="入口脚本不存在"):
            invoker.start(bad_manifest, tmp_path)

    def test_unsupported_entrypoint_type(self, tmp_path: Path) -> None:
        """不支持的 entrypoint 类型应抛出异常。"""
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
