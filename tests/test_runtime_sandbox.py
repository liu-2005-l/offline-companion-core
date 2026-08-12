"""运行时沙箱最小测试。"""

from __future__ import annotations

import builtins
import importlib
import socket
import sys
import urllib.request

import pytest

from offline_companion.shared.errors import SkillInvocationError
from offline_companion.shared.runtime_sandbox import (
    disable_runtime_sandbox,
    enable_runtime_sandbox,
    runtime_sandbox,
)

pytestmark = pytest.mark.security


def test_runtime_sandbox_blocks_dangerous_capabilities():
    enable_runtime_sandbox()
    try:
        with pytest.raises(SkillInvocationError):
            socket.socket()
        with pytest.raises(SkillInvocationError):
            urllib.request.urlopen("https://example.com")
        assert importlib.import_module("json").loads("{}") == {}
        assert importlib.import_module("sqlite3").connect(":memory:") is not None
        assert builtins.__import__("socket") is not None
        assert builtins.__import__("os") is not None
        with pytest.raises(SkillInvocationError):
            builtins.__import__("requests").get("https://example.com")
        with pytest.raises(SkillInvocationError):
            importlib.import_module("httpx")
        assert builtins.__import__("json").loads("{}") == {}
        assert builtins.__import__("sqlite3").connect(":memory:") is not None
        with pytest.raises(SkillInvocationError):
            builtins.eval("1 + 1")
        with pytest.raises(SkillInvocationError):
            builtins.exec("x = 1")
    finally:
        disable_runtime_sandbox()


def test_runtime_sandbox_context_manager_restores_state():
    with runtime_sandbox(), pytest.raises(SkillInvocationError):
        socket.socket()
    assert socket.socket is not None
    assert builtins.__import__("os") is not None


def test_runtime_sandbox_allows_local_socket_only():
    with runtime_sandbox(allow_local_socket=True):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            assert isinstance(sock.connect_ex(("127.0.0.1", 9)), int)
        with pytest.raises(SkillInvocationError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("93.184.216.34", 80))


def test_runtime_sandbox_restores_stubbed_network_modules():
    original = sys.modules.get("requests")
    with runtime_sandbox(allow_local_socket=True), pytest.raises(SkillInvocationError):
        sys.modules["requests"].get("https://example.com")
    assert sys.modules.get("requests") is original
