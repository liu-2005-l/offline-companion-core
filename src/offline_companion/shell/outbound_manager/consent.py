"""consent：Consent Artifact 构造与结构校验（A3）。"""

from __future__ import annotations

import sqlite3
from typing import Any

from offline_companion.shared.errors import ConsentArtifactError
from offline_companion.shared.types import PurposeType

_REQUIRED_KEYS = frozenset(
    {
        "request_id",
        "scope",
        "purpose",
        "user_decision",
        "timestamp",
        "data_category",
    }
)

_OPTIONAL_COMPAT_KEYS = frozenset({"purpose_type"})


def persist_consent_artifact(conn: sqlite3.Connection, artifact: dict[str, Any]) -> None:
    """摘要：校验 Artifact 并写入 C2 审计表（A3 编排 C2）。"""
    validate_consent_artifact(artifact)
    from offline_companion.runtime.storage_index.consent_store import store_consent_artifact

    store_consent_artifact(conn, artifact)


def validate_consent_artifact(artifact: dict[str, Any]) -> None:
    """摘要：校验 Artifact 最小字段集；通过后方可交由 C2 落库。

    参数：
        artifact: 待校验字典。

    异常：
        ConsentArtifactError：字段缺失或类型非法。
    """
    missing = sorted(_REQUIRED_KEYS - artifact.keys())
    if missing:
        raise ConsentArtifactError(f"Consent artifact missing keys: {missing}")
    if not isinstance(artifact.get("request_id"), str):
        raise ConsentArtifactError("request_id must be str")
    purpose = artifact.get("purpose") or artifact.get("purpose_type")
    if not isinstance(purpose, str) or purpose not in {m.value for m in PurposeType}:
        raise ConsentArtifactError(
            f"purpose/purpose_type 必须为合法 PurposeType 枚举值，当前为 {purpose!r}"
        )
    scope = artifact.get("scope")
    if not isinstance(scope, str) or not scope.strip():
        raise ConsentArtifactError("scope must be a non-empty str")
    artifact.setdefault("purpose_type", purpose)
