"""模型 Provider 注册表及热替换生命周期。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import RLock

from offline_companion.core.provider.types import ModelProvider, ProviderInfo


class ProviderNotFoundError(LookupError):
    """摘要：请求的 Provider 未注册。"""


@dataclass(frozen=True)
class ProviderRegistration:
    """摘要：Provider 及其注册时的元数据快照。"""

    info: ProviderInfo
    provider: ModelProvider


class ProviderRegistry:
    """摘要：线程安全的 Provider 注册、解析与原子替换服务。"""

    def __init__(self, providers: Iterable[ModelProvider] = ()) -> None:
        self._lock = RLock()
        self._providers: dict[str, ProviderRegistration] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ModelProvider) -> Callable[[], None]:
        """摘要：注册 Provider 并返回幂等释放器。

        异常：
            ValueError: Provider ID 为空或已被占用。
        """
        registration = self._registration(provider)
        provider_id = registration.info.provider_id
        with self._lock:
            if not provider_id:
                raise ValueError("Provider ID 不能为空")
            if provider_id in self._providers:
                raise ValueError(f"Provider 已注册: {provider_id}")
            self._providers[provider_id] = registration

        released = False

        def dispose() -> None:
            nonlocal released
            with self._lock:
                if released:
                    return
                released = True
                if self._providers.get(provider_id) is registration:
                    del self._providers[provider_id]

        return dispose

    def register_many(self, providers: Iterable[ModelProvider]) -> tuple[Callable[[], None], ...]:
        """摘要：原子注册一批 Provider，任何冲突都会全部回滚。"""
        registrations = tuple(self._registration(provider) for provider in providers)
        ids = [registration.info.provider_id for registration in registrations]
        if any(not provider_id for provider_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("Provider ID 必须非空且互不重复")
        with self._lock:
            if any(provider_id in self._providers for provider_id in ids):
                raise ValueError("Provider 已注册")
            self._providers.update(zip(ids, registrations))
        return tuple(self._disposer(registration) for registration in registrations)

    def resolve(self, provider_id: str) -> ProviderRegistration:
        """摘要：解析请求开始时的注册快照。

        异常：
            ProviderNotFoundError: Provider 不存在。
        """
        with self._lock:
            registration = self._providers.get(provider_id)
            if registration is None:
                raise ProviderNotFoundError(f"未找到 Provider: {provider_id}")
            return registration

    def replace(self, provider: ModelProvider) -> Callable[[], None]:
        """摘要：原子替换 Provider，新请求使用新实例，在途请求保留旧实例。"""
        registration = self._registration(provider)
        provider_id = registration.info.provider_id
        with self._lock:
            if not provider_id:
                raise ValueError("Provider ID 不能为空")
            self._providers[provider_id] = registration
        return self._disposer(registration)

    def _disposer(self, registration: ProviderRegistration) -> Callable[[], None]:
        provider_id = registration.info.provider_id
        released = False

        def dispose() -> None:
            nonlocal released
            with self._lock:
                if released:
                    return
                released = True
                if self._providers.get(provider_id) is registration:
                    del self._providers[provider_id]

        return dispose

    @staticmethod
    def _registration(provider: ModelProvider) -> ProviderRegistration:
        info = provider.info
        return ProviderRegistration(info=info, provider=provider)
