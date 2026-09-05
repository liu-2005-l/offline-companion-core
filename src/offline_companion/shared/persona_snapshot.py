"""摘要：人格快照来源枚举与旧值兼容映射。"""

from __future__ import annotations

from typing import Literal, cast

PERSONA_SNAPSHOT_SOURCE_A1 = "a1_persona_system_prompt"
PERSONA_SNAPSHOT_SOURCE_LEGACY = "legacy_backfill"
PERSONA_SNAPSHOT_SOURCE_L1 = "p3_a2_l1_assembled"

PersonaSnapshotSource = Literal[
    "a1_persona_system_prompt",
    "legacy_backfill",
    "p3_a2_l1_assembled",
]

PERSONA_SNAPSHOT_SOURCES = frozenset(
    {
        PERSONA_SNAPSHOT_SOURCE_A1,
        PERSONA_SNAPSHOT_SOURCE_LEGACY,
        PERSONA_SNAPSHOT_SOURCE_L1,
    }
)

LEGACY_PERSONA_SNAPSHOT_SOURCE_MAP = {
    "bootstrap": PERSONA_SNAPSHOT_SOURCE_A1,
    "persona_switch": PERSONA_SNAPSHOT_SOURCE_A1,
    "legacy_backfill": PERSONA_SNAPSHOT_SOURCE_LEGACY,
}


def normalize_persona_snapshot_source(source: str) -> PersonaSnapshotSource:
    """摘要：把旧来源值映射为冻结枚举并拒绝未知值。

    参数：
        source: 待校验或迁移的来源字符串。

    返回值：
        规范化后的人格快照来源。

    异常：
        ValueError：来源不在冻结枚举或旧值映射中。
    """
    normalized = LEGACY_PERSONA_SNAPSHOT_SOURCE_MAP.get(str(source), str(source))
    if normalized not in PERSONA_SNAPSHOT_SOURCES:
        raise ValueError(f"unsupported persona snapshot source: {source!r}")
    return cast(PersonaSnapshotSource, normalized)
