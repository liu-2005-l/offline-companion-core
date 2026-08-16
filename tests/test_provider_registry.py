from dataclasses import dataclass

import pytest

from offline_companion.core.provider import (
    ModelChunk,
    ModelRequest,
    ProviderInfo,
    ProviderNotFoundError,
    ProviderRegistry,
)
from offline_companion.shell.auto_router import AutoRouter


@dataclass
class _Provider:
    provider_id: str
    label: str = "provider"

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(self.provider_id, self.label)

    def generate(self, request: ModelRequest) -> str:
        return f"{self.label}:{request.user_message}"

    def generate_stream(self, request: ModelRequest):
        yield ModelChunk(self.generate(request))


def test_registry_resolves_and_disposes_idempotently() -> None:
    registry = ProviderRegistry()
    dispose = registry.register(_Provider("local", "旧"))

    assert registry.resolve("local").info.name == "旧"
    dispose()
    dispose()
    with pytest.raises(ProviderNotFoundError):
        registry.resolve("local")


def test_registry_rejects_duplicate_ids_and_batch_is_atomic() -> None:
    registry = ProviderRegistry([_Provider("local")])
    with pytest.raises(ValueError):
        registry.register(_Provider("local", "重复"))
    with pytest.raises(ValueError):
        registry.register_many([_Provider("cloud"), _Provider("local")])
    with pytest.raises(ProviderNotFoundError):
        registry.resolve("cloud")


def test_replace_keeps_old_registration_snapshot_alive() -> None:
    registry = ProviderRegistry([_Provider("local", "旧")])
    old_registration = registry.resolve("local")

    registry.replace(_Provider("local", "新"))

    assert old_registration.provider.generate(ModelRequest("消息")) == "旧:消息"
    assert registry.resolve("local").provider.generate(ModelRequest("消息")) == "新:消息"


def test_auto_router_resolves_provider_once_at_request_start() -> None:
    registry = ProviderRegistry([_Provider("local", "旧")])
    router = AutoRouter(provider_registry=registry)
    request = ModelRequest("消息", provider_id="local")
    snapshot = registry.resolve("local")
    registry.replace(_Provider("local", "新"))

    assert snapshot.provider.generate(request) == "旧:消息"
    assert router.chat(request) == "新:消息"
