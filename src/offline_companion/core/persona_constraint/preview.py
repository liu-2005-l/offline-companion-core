"""摘要：为自定义人格预览与持久化提供唯一确定性派生链。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from offline_companion.core.persona_constraint.levels import PersonaLevel, derive_levels

_TRAIT_LABELS = {
    "O": {"low": "务实守旧", "mid": "开放均衡", "high": "好奇心强"},
    "C": {"low": "随性自在", "mid": "张弛有度", "high": "有条理"},
    "E": {"low": "内敛安静", "mid": "互动适度", "high": "外向健谈"},
    "A": {"low": "直率独立", "mid": "边界清晰", "high": "温暖共情"},
    "N": {"low": "情绪稳定", "mid": "感受均衡", "high": "敏感丰富"},
}

_DESCRIPTION_LABELS = {
    "O": {"low": "务实，更关注眼前", "high": "对新事物充满好奇"},
    "C": {"low": "灵活随性，不拘小节", "high": "做事有条理、可靠"},
    "E": {"low": "内敛安静，善于观察", "high": "外向健谈，乐于表达"},
    "A": {"low": "独立直率，对事不对人", "high": "温暖友善，善于共情"},
    "N": {"low": "情绪稳定，波澜不惊", "high": "感受细腻，情绪丰富"},
}


@dataclass(frozen=True)
class PersonaPreview:
    """摘要：前端预览与最终保存共同消费的派生结果。"""

    name: str
    ocean: tuple[int, int, int, int, int]
    traits: tuple[str, ...]
    description: str
    system_prompt: str

    def as_payload(self) -> dict[str, object]:
        """摘要：返回可直接序列化到本地 HTTP API 的 payload。"""
        return {
            "name": self.name,
            "ocean": list(self.ocean),
            "traits": list(self.traits),
            "desc": self.description,
            "anchor": self.system_prompt,
        }


def derive_persona_preview(name: object, ocean_values: object) -> PersonaPreview:
    """摘要：从名称和 OCEAN 向量确定性派生展示标签、描述与系统提示。

    参数：
        name: 非空人格名称。
        ocean_values: 长度为 5 的 0..100 整数列表。

    返回值：
        不含 IO、时间或随机状态的派生结果。

    Raises:
        ValueError: 名称或 OCEAN 向量不合法。
    """
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise ValueError("name_required")
    if not isinstance(ocean_values, list) or any(
        type(value) is not int for value in ocean_values
    ):
        raise ValueError("persona_ocean_vector_invalid")
    levels = derive_levels(ocean_values)
    ocean = tuple(ocean_values)
    if len(ocean) != 5:
        raise ValueError("persona_ocean_vector_invalid")

    traits = tuple(_TRAIT_LABELS[dimension][level] for dimension, level in levels.items())
    description_parts = [
        _DESCRIPTION_LABELS[dimension][level]
        for dimension, level in levels.items()
        if level != "mid"
    ]
    description = "，".join(description_parts or ["性格均衡，没有极端倾向"]) + "。"
    system_prompt = _build_system_prompt(normalized_name, levels)
    return PersonaPreview(
        name=normalized_name,
        ocean=ocean,
        traits=traits,
        description=description,
        system_prompt=system_prompt,
    )


def _build_system_prompt(name: str, levels: Mapping[str, PersonaLevel]) -> str:
    if levels["E"] == "high" and levels["A"] == "high":
        interaction = "主动关心用户，语气温暖亲切"
    elif levels["E"] == "high":
        interaction = "主动发起话题，语气轻快"
    elif levels["A"] == "high":
        interaction = "在用户需要时给予温暖回应"
    else:
        interaction = "回答简洁直接，不主动展开"

    if levels["N"] == "high":
        emotion = "留意细微的情绪变化"
    elif levels["N"] == "low":
        emotion = "保持冷静稳定的陪伴"
    else:
        emotion = "保持平稳并适时回应"

    if levels["O"] == "high":
        expression = "表达可以使用自然的比喻和意象"
    elif levels["O"] == "low":
        expression = "表达务实清楚，不刻意炫技"
    else:
        expression = "表达自然，不刻意修饰"
    return f"你是{name}。{interaction}；{emotion}；{expression}。始终按这些人格档位回应。"
