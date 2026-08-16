"""Provider 抽象的公共类型。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from offline_companion.shared.types import MessageRow


@dataclass(frozen=True)
class ProviderInfo:
    """摘要：描述一个可供路由的模型提供者。

    参数：
        provider_id: 稳定的提供者标识。
        name: 面向界面的显示名称。
        kind: 提供者类型，例如 ``local`` 或 ``cloud``。
        metadata: 提供者的扩展元数据。
    """

    provider_id: str
    name: str = ""
    kind: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelRequest:
    """摘要：一次模型生成请求的不可变快照。"""

    user_message: str
    system_prompt: str = ""
    history: list[MessageRow] = field(default_factory=list)
    memory_block: str = ""
    max_tokens: int = 256
    provider_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelChunk:
    """摘要：流式生成返回的一个文本片段。"""

    text: str
    finish_reason: str | None = None


class ModelProvider(Protocol):
    """摘要：统一模型提供者协议。

    提供者实例在注册后可被在途请求持有；替换注册不会中断这些请求。
    """

    @property
    def info(self) -> ProviderInfo: ...

    def generate(self, request: ModelRequest) -> str: ...

    def generate_stream(self, request: ModelRequest) -> Iterator[ModelChunk]: ...
