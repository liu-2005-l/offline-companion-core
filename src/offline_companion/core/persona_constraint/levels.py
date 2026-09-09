"""摘要：按冻结切点从 OCEAN 数值确定性派生人格档位。"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Literal

DIMENSION_ORDER = ("O", "C", "E", "A", "N")
CUTPOINT_VERSION = "p3_a2_cutpoints_v1"

PersonaLevel = Literal["low", "mid", "high"]


class PersonaLevelDerivationError(ValueError):
    """摘要：OCEAN 数值无法按冻结切点派生。"""


def to_level(value: object) -> PersonaLevel:
    """摘要：将单个 0..100 OCEAN 数值映射为冻结档位。

    参数：
        value: 有限数值；布尔值不视为整数。

    返回值：
        `low`、`mid` 或 `high`。

    Raises:
        PersonaLevelDerivationError: 数值类型非法、非有限或越界。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PersonaLevelDerivationError("persona_ocean_value_invalid")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0 or numeric > 100:
        raise PersonaLevelDerivationError("persona_ocean_value_invalid")
    if numeric <= 33:
        return "low"
    if numeric <= 66:
        return "mid"
    return "high"


def derive_levels(ocean_values: Sequence[object]) -> dict[str, PersonaLevel]:
    """摘要：按 O/C/E/A/N 固定顺序派生五维档位。

    参数：
        ocean_values: 长度恰为 5 的 0..100 数值序列。

    返回值：
        维度到冻结档位的确定性映射。

    Raises:
        PersonaLevelDerivationError: 长度、类型或数值不合法。
    """
    if (
        not isinstance(ocean_values, Sequence)
        or isinstance(ocean_values, (str, bytes))
        or len(ocean_values) != len(DIMENSION_ORDER)
    ):
        raise PersonaLevelDerivationError("persona_ocean_vector_invalid")
    return {
        dimension: to_level(value)
        for dimension, value in zip(DIMENSION_ORDER, ocean_values, strict=True)
    }


def serialize_levels(levels: dict[str, PersonaLevel]) -> str:
    """摘要：稳定序列化完整五维档位缓存。

    参数：
        levels: 完整且仅含 O/C/E/A/N 的档位映射。

    返回值：
        可逐字节比较的 canonical JSON。

    Raises:
        PersonaLevelDerivationError: 维度集合或档位值不合法。
    """
    if tuple(levels) != DIMENSION_ORDER:
        raise PersonaLevelDerivationError("persona_level_dimensions_invalid")
    if any(level not in {"low", "mid", "high"} for level in levels.values()):
        raise PersonaLevelDerivationError("persona_level_value_invalid")
    return json.dumps(levels, ensure_ascii=False, separators=(",", ":"))
