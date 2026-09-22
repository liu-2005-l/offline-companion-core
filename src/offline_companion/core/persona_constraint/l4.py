"""摘要：人格约束 L4 冻结扫描策略与确定性动作结果。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from offline_companion.core.persona_constraint.assets import PersonaConstraintAssets
from offline_companion.core.persona_constraint.lint import scan_l4

L4_DIRECT = "direct"
L4_RETRY = "retry"
L4_FALLBACK = "fallback"
L4_OBSERVE = "observe"
L4_BYPASS = "bypass"
L4_IDENTITY_CLIFF = "identity_cliff"
L4_CAPABILITY_AND_FACT_DENIAL = "capability_and_fact_denial"
L4_USER_ATTACK = "user_attack"

PersonaL4Action = Literal["direct", "retry", "observe"]
PersonaL4Outcome = Literal["bypass", "direct", "retry", "fallback", "observe"]


class PersonaL4ConfigError(ValueError):
    """摘要：L4 冻结模式资产结构无效。"""


@dataclass(frozen=True)
class PersonaL4Policy:
    """摘要：通过发布哈希校验的 L4 三分区扫描策略。"""

    patterns: Mapping[str, Any]


@dataclass(frozen=True)
class PersonaL4Decision:
    """摘要：一次 L4 纯扫描的动作与命中来源。"""

    action: PersonaL4Action
    zone: str | None = None
    family: str | None = None


@dataclass(frozen=True)
class PersonaL4Trace:
    """摘要：记录 L4 direct/retry/fallback/observe 的最终执行形态。"""

    enabled: bool = False
    buffered: bool = False
    outcome: PersonaL4Outcome = L4_BYPASS
    first_zone: str | None = None
    first_family: str | None = None
    retry_zone: str | None = None
    retry_family: str | None = None
    retry_taken: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)


def policy_from_assets(assets: PersonaConstraintAssets) -> PersonaL4Policy:
    """摘要：从完整根资产构造并校验 L4 冻结策略。

    参数：
        assets: 已通过发布 manifest 与逐源哈希校验的资产集合。
    返回值：
        只读 L4 策略。
    Raises:
        PersonaL4ConfigError: 模式分区或动作与 P1 冻结口径不一致。
    """
    payload = assets.source_payloads.get("l4_patterns")
    if not isinstance(payload, Mapping):
        raise PersonaL4ConfigError("l4_patterns_missing")
    zones = payload.get("zones")
    if not isinstance(zones, Mapping):
        raise PersonaL4ConfigError("l4_zones_invalid")
    expected_actions = {
        L4_IDENTITY_CLIFF: "retry_then_fallback",
        L4_CAPABILITY_AND_FACT_DENIAL: "retry_then_fallback",
        L4_USER_ATTACK: "observe_only",
    }
    if set(zones) != set(expected_actions):
        raise PersonaL4ConfigError("l4_zones_mismatch")
    for zone_name, expected_action in expected_actions.items():
        zone = zones.get(zone_name)
        if not isinstance(zone, Mapping) or zone.get("action") != expected_action:
            raise PersonaL4ConfigError(f"l4_action_invalid:{zone_name}")
        families = zone.get("families")
        if not isinstance(families, Mapping) or not families:
            raise PersonaL4ConfigError(f"l4_families_invalid:{zone_name}")
    return PersonaL4Policy(patterns=MappingProxyType(dict(payload)))


def resolve_l4(text: str, policy: PersonaL4Policy, *, display_name: str) -> PersonaL4Decision:
    """摘要：扫描最终候选并返回冻结的 direct/retry/observe 动作。

    参数：
        text: 待放行的最终候选文本。
        policy: 已校验 L4 策略。
        display_name: 当前会话烧入自称。
    返回值：
        不含副作用的 L4 判定。
    """
    compact_name = "".join(str(display_name or "").split())
    compact_text = "".join(str(text or "").split())
    result = scan_l4(
        str(text or ""),
        policy.patterns,
        display_name_present=bool(compact_name and compact_name in compact_text),
    )
    if not result.get("hit"):
        return PersonaL4Decision(action=L4_DIRECT)
    zone = str(result.get("zone") or "invalid")
    family = str(result.get("family") or "invalid")
    if zone == L4_USER_ATTACK:
        return PersonaL4Decision(action=L4_OBSERVE, zone=zone, family=family)
    return PersonaL4Decision(action=L4_RETRY, zone=zone, family=family)


def build_l4_retry_instruction(display_name: str) -> str:
    """摘要：构造一次性 L4 重试提醒，不写入历史。"""
    return (
        "【人格约束重试提醒 data-ephemeral】\n"
        "上一次候选出现身份或能力事实边界偏移。请重新直接回答原问题：准确优先，"
        f"保持当前自称“{display_name}”与既定人格；不要否认已存在且经授权的本地能力；"
        "不确定时明确边界，不编造。"
    )


def deterministic_l4_fallback(zone: str | None, display_name: str) -> str:
    """摘要：按首次命中分区返回不含模型输出的确定性降级正文。"""
    if zone == L4_IDENTITY_CLIFF:
        return (
            f"AI 身份不会被隐瞒；当前会话中我会保持“{display_name}”这一身份与既定人格，"
            "同时以事实和安全边界为先。"
        )
    return (
        "这次回复没有守住能力与事实边界，我先不沿用它。"
        "当前能力以本机实际启用的功能和你的授权为准；不确定的部分我会明确说明，不把否认当成事实。"
    )
