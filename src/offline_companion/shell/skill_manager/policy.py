"""policy：Skill permissions × 隐私模式策略（A2；不发起网络）。"""

from __future__ import annotations

from dataclasses import dataclass

from offline_companion.shared.errors import SkillPolicyDenied
from offline_companion.shared.types import PrivacyMode

from .manifest import SkillManifest

PERM_CLOUD = "cloud_inference"
PERM_NETWORK = "network_egress"
PERM_READ_CTX = "read_session_context"

_LOCAL_ONLY_DENY_MSG = "当前隐私模式下不可用"


@dataclass(frozen=True)
class SkillPolicyResult:
    """摘要：策略评估结果（调用方据此走 Consent / 阻断）。"""

    allowed: bool
    requires_consent: bool
    purpose_hint: str | None
    reason: str


def check_read_context(manifest: SkillManifest, privacy_mode: PrivacyMode) -> bool:
    """摘要：是否允许向 Skill 注入会话上下文（Sprint 8 ``inject_context`` 接缝）。

    MVP 阶段恒为 ``False``；调用方应以此为准，勿自行解析 ``read_session_context``。
    """
    _ = manifest, privacy_mode
    return False


def evaluate_skill_policy(
    manifest: SkillManifest,
    *,
    privacy_mode: PrivacyMode,
) -> SkillPolicyResult:
    """摘要：评估在当前隐私模式下是否允许调用该 Skill。

    权限矩阵（MVP）：
        - ``network_egress`` + ``LOCAL_ONLY`` → 硬拒绝，不生成 Consent
        - ``cloud_inference`` + ``LOCAL_ONLY`` → 硬拒绝，不生成 Consent
        - ``cloud_inference`` + 其他模式 → 允许，须 ``skill_cloud_call`` Consent
        - 纯本地 Skill → ``skill_invoke``
    """
    perms = set(manifest.permissions)

    if privacy_mode == PrivacyMode.LOCAL_ONLY:
        if PERM_NETWORK in perms or PERM_CLOUD in perms:
            return SkillPolicyResult(
                allowed=False,
                requires_consent=False,
                purpose_hint=None,
                reason=_LOCAL_ONLY_DENY_MSG,
            )

    if PERM_CLOUD in perms:
        return SkillPolicyResult(
            allowed=True,
            requires_consent=True,
            purpose_hint="skill_cloud_call",
            reason="Skill 声明 cloud_inference，须经 A3 Consent",
        )

    return SkillPolicyResult(
        allowed=True,
        requires_consent=False,
        purpose_hint="skill_invoke",
        reason="本地 Skill 调用",
    )


def require_skill_allowed(
    manifest: SkillManifest,
    *,
    privacy_mode: PrivacyMode,
) -> SkillPolicyResult:
    """摘要：评估策略；不允许时抛出 ``SkillPolicyDenied``。"""
    result = evaluate_skill_policy(manifest, privacy_mode=privacy_mode)
    if not result.allowed:
        raise SkillPolicyDenied(result.reason)
    return result
