"""摘要：A3 云端连接器（Sprint 2）。"""

from __future__ import annotations

import pytest

from offline_companion.shared.errors import CloudConnectorError
from offline_companion.shared.types import CloudCompletionRequest
from offline_companion.shell.outbound_manager.connector import post_cloud_completion


def test_cloud_stub_mode(monkeypatch) -> None:
    monkeypatch.setenv("OFFLINE_COMPANION_CLOUD_STUB", "1")
    monkeypatch.delenv("OFFLINE_COMPANION_CLOUD_URL", raising=False)
    resp = post_cloud_completion(
        CloudCompletionRequest(user_message="你好", purpose="test"),
    )
    assert resp.text
    assert resp.raw.get("stub") is True


def test_cloud_missing_url_raises(monkeypatch) -> None:
    monkeypatch.delenv("OFFLINE_COMPANION_CLOUD_STUB", raising=False)
    monkeypatch.delenv("OFFLINE_COMPANION_CLOUD_URL", raising=False)
    with pytest.raises(CloudConnectorError):
        post_cloud_completion(CloudCompletionRequest(user_message="x", purpose="t"))
