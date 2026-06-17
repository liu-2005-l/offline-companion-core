"""manifest：Skill manifest 强类型 DTO（A2；不含网络或执行逻辑）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from offline_companion.shared.errors import SkillManifestError

if TYPE_CHECKING:
    from packaging.version import Version

_ALLOWED_ENTRYPOINT_HOST = "127.0.0.1"


@dataclass(frozen=True)
class SkillEntrypoint:
    """摘要：Skill 本地 API 入口描述。

    ``host`` 在构造时强制为 ``127.0.0.1``（不依赖 Schema enum 作为唯一防线）。
    """

    type: str
    host: str
    port: int
    path: str

    def __post_init__(self) -> None:
        if self.host != _ALLOWED_ENTRYPOINT_HOST:
            raise SkillManifestError(
                f"entrypoint.host 仅限 {_ALLOWED_ENTRYPOINT_HOST!r}，当前为 {self.host!r}"
            )


@dataclass(frozen=True)
class SkillManifest:
    """摘要：已通过 registry 校验的 Skill manifest。

    ``version`` 字段为 ``packaging.version.Version`` 对象，禁止在 DTO 层使用字符串版本。
    """

    name: str
    version: Version
    version_raw: str
    description: str
    market_id: str
    trust: str
    entrypoint: SkillEntrypoint
    permissions: tuple[str, ...]
    required_api_keys: tuple[str, ...]
    output_mode: str
    raw: dict[str, Any]
