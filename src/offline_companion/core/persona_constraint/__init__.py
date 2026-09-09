"""摘要：人格约束冻结资产加载与确定性派生入口。"""

from offline_companion.core.persona_constraint.assembly import (
    DISPLAY_NAME_PLACEHOLDER,
    FROZEN_MAPPING_COMMIT,
    L1_PROMPT_CHARACTER_LIMIT,
    AssembledPrompt,
    FrozenL1Mapping,
    PersonaL1AssemblyError,
    assemble_l1_prompt,
    default_frozen_l1_mapping,
    finalize_l1_prompt,
)
from offline_companion.core.persona_constraint.assets import (
    PERSONA_CONSTRAINT_MANIFEST_SHA256,
    REPLY_COPY_CONSTRAINT_CONFIG_FALLBACK,
    REPLY_COPY_MEMORY_SAVED_CONFIRMATION,
    REPLY_COPY_SWITCH_CONFIRMATION,
    BuiltinPersonaPreset,
    PersonaConstraintAssets,
    PersonaConstraintConfigError,
    PersonaReplyCopy,
    ReplyCopyKind,
    load_persona_constraint_assets,
)
from offline_companion.core.persona_constraint.levels import (
    CUTPOINT_VERSION,
    DIMENSION_ORDER,
    PersonaLevelDerivationError,
    derive_levels,
    serialize_levels,
    to_level,
)
from offline_companion.core.persona_constraint.preview import (
    PersonaPreview,
    derive_persona_preview,
)

__all__ = [
    "CUTPOINT_VERSION",
    "DIMENSION_ORDER",
    "DISPLAY_NAME_PLACEHOLDER",
    "FROZEN_MAPPING_COMMIT",
    "L1_PROMPT_CHARACTER_LIMIT",
    "PERSONA_CONSTRAINT_MANIFEST_SHA256",
    "REPLY_COPY_CONSTRAINT_CONFIG_FALLBACK",
    "REPLY_COPY_MEMORY_SAVED_CONFIRMATION",
    "REPLY_COPY_SWITCH_CONFIRMATION",
    "AssembledPrompt",
    "BuiltinPersonaPreset",
    "FrozenL1Mapping",
    "PersonaConstraintAssets",
    "PersonaConstraintConfigError",
    "PersonaL1AssemblyError",
    "PersonaLevelDerivationError",
    "PersonaPreview",
    "PersonaReplyCopy",
    "ReplyCopyKind",
    "assemble_l1_prompt",
    "default_frozen_l1_mapping",
    "derive_levels",
    "derive_persona_preview",
    "finalize_l1_prompt",
    "load_persona_constraint_assets",
    "serialize_levels",
    "to_level",
]
