"""运行时沙箱最小测试。"""

from __future__ import annotations

import builtins
import importlib
import socket
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
        with pytest.raises(SkillInvocationError):
            importlib.import_module("json")
        with pytest.raises(SkillInvocationError):
            builtins.eval("1 + 1")
        with pytest.raises(SkillInvocationError):
            builtins.exec("x = 1")
    finally:
        disable_runtime_sandbox()


def test_runtime_sandbox_context_manager_restores_state():
    with runtime_sandbox():
        with pytest.raises(SkillInvocationError):
            socket.socket()
    assert socket.socket is not None
