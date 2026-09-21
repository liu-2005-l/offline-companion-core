"""摘要：按冻结组合机械组装确定性 L1 人格提示词。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from offline_companion.core.persona_constraint.assets import PersonaConstraintAssets
from offline_companion.core.persona_constraint.levels import DIMENSION_ORDER, PersonaLevel

FROZEN_MAPPING_COMMIT = "883f84b"
L1_PROMPT_CHARACTER_LIMIT = 660
DISPLAY_NAME_PLACEHOLDER = "{display_name}"


class PersonaL1AssemblyError(RuntimeError):
    """摘要：冻结 L1 映射、引用或字符预算不满足契约。"""


@dataclass(frozen=True)
class FrozenL1Mapping:
    """摘要：单轮 L1 组装使用的冻结引用与派生档位。"""

    persona_id: str
    persona_name: str
    levels: tuple[PersonaLevel, PersonaLevel, PersonaLevel, PersonaLevel, PersonaLevel]
    traits: tuple[str, ...]
    dimension_dialogue_ids: tuple[str, str, str, str, str]
    structural_sample_id: str


@dataclass(frozen=True)
class AssembledPrompt:
    """摘要：L1 纯函数产物及不进入模型文本的引用 trace。"""

    persona_id: str
    text: str
    character_count: int
    manifest_sha256: str
    frozen_mapping_commit: str
    dimension_dialogue_ids: tuple[str, str, str, str, str]
    structural_sample_id: str


def default_frozen_l1_mapping(
    persona_id: str,
    corpus_assets: PersonaConstraintAssets,
) -> FrozenL1Mapping:
    """摘要：按 composition YAML 顺序机械选择默认五维与诚实样本。

    参数：
        persona_id: 五个 validated anchor 之一的稳定 ID。
        corpus_assets: 已通过完整根与哈希校验的冻结资产。

    返回值：
        可供 L1 纯组装器消费的默认冻结映射。

    Raises:
        PersonaL1AssemblyError: 人格或 composition 结构不完整。
    """
    preset = next(
        (item for item in corpus_assets.builtin_presets if item.persona_id == persona_id),
        None,
    )
    if preset is None:
        raise PersonaL1AssemblyError(f"persona_l1_not_validated:{persona_id}")
    compositions = _mapping(
        corpus_assets.source_payloads["persona_compositions"].get("personas"),
        "persona_l1_compositions_invalid",
    )
    composition = _mapping(
        compositions.get(preset.name),
        f"persona_l1_composition_missing:{persona_id}",
    )
    dimension_refs = _mapping(
        composition.get("dimension_dialogue_refs"),
        f"persona_l1_dimension_refs_invalid:{persona_id}",
    )
    dialogue_ids: list[str] = []
    for dimension in DIMENSION_ORDER:
        reference = _mapping(
            dimension_refs.get(dimension),
            f"persona_l1_dimension_ref_missing:{persona_id}:{dimension}",
        )
        candidates = _string_sequence(
            reference.get("dialogues"),
            f"persona_l1_dialogue_refs_invalid:{persona_id}:{dimension}",
        )
        dialogue_ids.append(candidates[0])
    structural_refs = _mapping(
        composition.get("structural_sample_refs"),
        f"persona_l1_structural_refs_invalid:{persona_id}",
    )
    honesty_ids = _string_sequence(
        structural_refs.get("honesty"),
        f"persona_l1_honesty_refs_invalid:{persona_id}",
    )
    return FrozenL1Mapping(
        persona_id=persona_id,
        persona_name=preset.name,
        levels=preset.levels,
        traits=preset.derived_traits,
        dimension_dialogue_ids=tuple(dialogue_ids),
        structural_sample_id=honesty_ids[0],
    )


def l3_frozen_l1_mapping(
    persona_id: str,
    corpus_assets: PersonaConstraintAssets,
    trigger_domain: str,
) -> FrozenL1Mapping:
    """摘要：为逐轮 L3 触发机械替换唯一授权的降档结构样本。

    参数：
        persona_id: 当前 validated anchor 稳定 ID。
        corpus_assets: 已通过完整根与哈希校验的冻结资产。
        trigger_domain: ``low_intensity_comfort`` 或 ``low_intensity_correction``。
    返回值：
        仅结构样本引用不同于 A2 默认映射的不可变映射。
    Raises:
        PersonaL1AssemblyError: 触发域未知或人格没有对应冻结样本。
    """
    if trigger_domain not in {"low_intensity_comfort", "low_intensity_correction"}:
        raise PersonaL1AssemblyError(f"persona_l3_trigger_domain_invalid:{trigger_domain}")
    default = default_frozen_l1_mapping(persona_id, corpus_assets)
    composition = _persona_composition(corpus_assets, default.persona_name, persona_id)
    references = _mapping(
        composition.get("structural_sample_refs"),
        f"persona_l1_structural_refs_invalid:{persona_id}",
    )
    candidates = _string_sequence(
        references.get("downgrade"),
        f"persona_l3_downgrade_refs_invalid:{persona_id}",
    )
    structural_index = _structural_sample_index(corpus_assets)
    sample_id = next(
        (
            candidate
            for candidate in candidates
            if structural_index.get(candidate, {}).get("trigger_domain") == trigger_domain
        ),
        None,
    )
    if sample_id is None:
        raise PersonaL1AssemblyError(
            f"persona_l3_downgrade_sample_missing:{persona_id}:{trigger_domain}"
        )
    return replace(default, structural_sample_id=sample_id)


def assemble_l1_prompt(
    persona_id: str,
    corpus_assets: PersonaConstraintAssets,
    frozen_mapping: FrozenL1Mapping,
) -> AssembledPrompt:
    """摘要：无 IO、无时间与随机状态地组装完整 L1 文本块。

    参数：
        persona_id: 当前 validated anchor 稳定 ID。
        corpus_assets: 已通过完整根与哈希校验的冻结资产。
        frozen_mapping: L3 上游确定后交给本函数的具体引用映射。

    返回值：
        确定性文本与独立 trace。

    Raises:
        PersonaL1AssemblyError: 映射漂移、引用悬空、文本非法或超预算。
    """
    preset = next(
        (item for item in corpus_assets.builtin_presets if item.persona_id == persona_id),
        None,
    )
    if preset is None:
        raise PersonaL1AssemblyError(f"persona_l1_not_validated:{persona_id}")
    if frozen_mapping.persona_id != persona_id or frozen_mapping.persona_name != preset.name:
        raise PersonaL1AssemblyError(f"persona_l1_mapping_identity_mismatch:{persona_id}")
    if frozen_mapping.levels != preset.levels or frozen_mapping.traits != preset.derived_traits:
        raise PersonaL1AssemblyError(f"persona_l1_mapping_profile_mismatch:{persona_id}")

    composition = _persona_composition(corpus_assets, preset.name, persona_id)
    dimension_index = _dimension_dialogue_index(corpus_assets)
    rendered_blocks: list[str] = []
    for index, dimension in enumerate(DIMENSION_ORDER):
        dialogue_id = frozen_mapping.dimension_dialogue_ids[index]
        _validate_dimension_reference(
            composition,
            persona_id=persona_id,
            dimension=dimension,
            level=frozen_mapping.levels[index],
            dialogue_id=dialogue_id,
        )
        dialogue = dimension_index.get(dialogue_id)
        if dialogue is None:
            raise PersonaL1AssemblyError(f"persona_l1_dialogue_missing:{dialogue_id}")
        rendered_blocks.append(_render_turns(dialogue, dialogue_id))

    structural_index = _structural_sample_index(corpus_assets)
    _validate_structural_reference(
        composition,
        persona_id=persona_id,
        sample_id=frozen_mapping.structural_sample_id,
    )
    structural = structural_index.get(frozen_mapping.structural_sample_id)
    if structural is None:
        raise PersonaL1AssemblyError(
            f"persona_l1_structural_sample_missing:{frozen_mapping.structural_sample_id}"
        )
    rendered_blocks.append(_render_turns(structural, frozen_mapping.structural_sample_id))

    levels_text = ",".join(
        f"{dimension}={level}"
        for dimension, level in zip(DIMENSION_ORDER, frozen_mapping.levels, strict=True)
    )
    traits_text = ",".join(frozen_mapping.traits)
    text = "\n".join(
        (
            preset.base_system_prompt,
            f"档位:{levels_text}",
            "\n\n".join(rendered_blocks),
            f"标签:{traits_text}",
        )
    )
    return AssembledPrompt(
        persona_id=persona_id,
        text=text,
        character_count=len(text),
        manifest_sha256=corpus_assets.manifest_sha256,
        frozen_mapping_commit=FROZEN_MAPPING_COMMIT,
        dimension_dialogue_ids=frozen_mapping.dimension_dialogue_ids,
        structural_sample_id=frozen_mapping.structural_sample_id,
    )


def finalize_l1_prompt(assembled_prompt: AssembledPrompt, display_name: str) -> str:
    """摘要：烧入已净化自称并校验最终生效 L1 文本预算。

    参数：
        assembled_prompt: 保留自称占位符的纯组装产物。
        display_name: 已按会话身份规则净化的非空自称。

    返回值：
        不含自称占位符且不超过字符预算的最终 L1 文本。

    Raises:
        PersonaL1AssemblyError: 自称或占位符不满足契约，或烧入态文本超预算。
    """
    normalized_name = str(display_name).strip()
    if not normalized_name or "\n" in normalized_name or "\r" in normalized_name:
        raise PersonaL1AssemblyError("persona_l1_display_name_invalid")
    if assembled_prompt.text.count(DISPLAY_NAME_PLACEHOLDER) != 1:
        raise PersonaL1AssemblyError("persona_l1_display_name_placeholder_invalid")
    text = assembled_prompt.text.replace(DISPLAY_NAME_PLACEHOLDER, normalized_name)
    if len(text) > L1_PROMPT_CHARACTER_LIMIT:
        raise PersonaL1AssemblyError(
            f"persona_l1_prompt_over_budget:{assembled_prompt.persona_id}:{len(text)}"
        )
    return text


def _persona_composition(
    assets: PersonaConstraintAssets,
    persona_name: str,
    persona_id: str,
) -> Mapping[str, Any]:
    compositions = _mapping(
        assets.source_payloads["persona_compositions"].get("personas"),
        "persona_l1_compositions_invalid",
    )
    return _mapping(
        compositions.get(persona_name),
        f"persona_l1_composition_missing:{persona_id}",
    )


def _dimension_dialogue_index(assets: PersonaConstraintAssets) -> dict[str, Mapping[str, Any]]:
    units = _mapping(
        assets.source_payloads["dimension_corpus"].get("dimension_units"),
        "persona_l1_dimension_units_invalid",
    )
    result: dict[str, Mapping[str, Any]] = {}
    for dimension in DIMENSION_ORDER:
        levels = _mapping(units.get(dimension), f"persona_l1_dimension_missing:{dimension}")
        for level in ("low", "mid", "high"):
            unit = _mapping(levels.get(level), f"persona_l1_unit_missing:{dimension}:{level}")
            dialogues = _mapping_sequence(
                unit.get("dialogues"),
                f"persona_l1_dialogues_invalid:{dimension}:{level}",
            )
            for dialogue in dialogues:
                dialogue_id = dialogue.get("id")
                if not isinstance(dialogue_id, str) or not dialogue_id:
                    raise PersonaL1AssemblyError("persona_l1_dialogue_id_invalid")
                if dialogue_id in result:
                    raise PersonaL1AssemblyError(f"persona_l1_dialogue_duplicate:{dialogue_id}")
                result[dialogue_id] = dialogue
    return result


def _structural_sample_index(assets: PersonaConstraintAssets) -> dict[str, Mapping[str, Any]]:
    categories = _mapping(
        assets.source_payloads["structural_corpus"].get("structural_samples"),
        "persona_l1_structural_samples_invalid",
    )
    result: dict[str, Mapping[str, Any]] = {}
    for samples_value in categories.values():
        samples = _mapping_sequence(samples_value, "persona_l1_structural_category_invalid")
        for sample in samples:
            sample_id = sample.get("id")
            if not isinstance(sample_id, str) or not sample_id:
                raise PersonaL1AssemblyError("persona_l1_structural_id_invalid")
            if sample_id in result:
                raise PersonaL1AssemblyError(f"persona_l1_structural_duplicate:{sample_id}")
            result[sample_id] = sample
    return result


def _validate_dimension_reference(
    composition: Mapping[str, Any],
    *,
    persona_id: str,
    dimension: str,
    level: PersonaLevel,
    dialogue_id: str,
) -> None:
    levels = _mapping(composition.get("levels"), f"persona_l1_levels_invalid:{persona_id}")
    if levels.get(dimension) != level:
        raise PersonaL1AssemblyError(
            f"persona_l1_dimension_level_mismatch:{persona_id}:{dimension}"
        )
    references = _mapping(
        composition.get("dimension_dialogue_refs"),
        f"persona_l1_dimension_refs_invalid:{persona_id}",
    )
    reference = _mapping(
        references.get(dimension),
        f"persona_l1_dimension_ref_missing:{persona_id}:{dimension}",
    )
    expected_unit = f"{dimension}_{level}"
    if reference.get("unit") != expected_unit:
        raise PersonaL1AssemblyError(
            f"persona_l1_dimension_unit_mismatch:{persona_id}:{dimension}"
        )
    allowed = _string_sequence(
        reference.get("dialogues"),
        f"persona_l1_dialogue_refs_invalid:{persona_id}:{dimension}",
    )
    if dialogue_id not in allowed:
        raise PersonaL1AssemblyError(
            f"persona_l1_dialogue_not_authorized:{persona_id}:{dimension}:{dialogue_id}"
        )


def _validate_structural_reference(
    composition: Mapping[str, Any],
    *,
    persona_id: str,
    sample_id: str,
) -> None:
    references = _mapping(
        composition.get("structural_sample_refs"),
        f"persona_l1_structural_refs_invalid:{persona_id}",
    )
    allowed = {
        item
        for values in references.values()
        for item in _string_sequence(values, f"persona_l1_structural_refs_invalid:{persona_id}")
    }
    if sample_id not in allowed:
        raise PersonaL1AssemblyError(
            f"persona_l1_structural_not_authorized:{persona_id}:{sample_id}"
        )


def _render_turns(sample: Mapping[str, Any], sample_id: str) -> str:
    turns = _mapping_sequence(sample.get("turns"), f"persona_l1_turns_invalid:{sample_id}")
    if not 2 <= len(turns) <= 3:
        raise PersonaL1AssemblyError(f"persona_l1_turn_count_invalid:{sample_id}")
    lines: list[str] = []
    for turn in turns:
        user = turn.get("user")
        assistant = turn.get("assistant")
        if not isinstance(user, str) or not user or not isinstance(assistant, str) or not assistant:
            raise PersonaL1AssemblyError(f"persona_l1_turn_text_invalid:{sample_id}")
        lines.extend((f"U:{user}", f"A:{assistant}"))
    return "\n".join(lines)


def _mapping(value: Any, error: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PersonaL1AssemblyError(error)
    return value


def _mapping_sequence(value: Any, error: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PersonaL1AssemblyError(error)
    result: list[Mapping[str, Any]] = []
    for item in value:
        result.append(_mapping(item, error))
    if not result:
        raise PersonaL1AssemblyError(error)
    return tuple(result)


def _string_sequence(value: Any, error: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PersonaL1AssemblyError(error)
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise PersonaL1AssemblyError(error)
    return result
