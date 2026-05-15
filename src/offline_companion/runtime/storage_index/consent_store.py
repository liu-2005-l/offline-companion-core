"""consent_store：Consent Artifact 持久化（C2；无策略判断）。"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any


def store_consent_artifact(conn: sqlite3.Connection, artifact: dict[str, Any]) -> None:
    """摘要：将已通过 A3 校验的 Artifact 写入审计表。

    参数：
        conn: SQLite 连接。
        artifact: 已验证字典（将整体序列化为 JSON 落库）。

    说明：不做字段存在性校验；序列化失败将自然抛出异常。
    """
    json.dumps(artifact)  # 序列化探测，避免损坏数据落库
    rid = str(artifact.get("request_id") or "")
    conn.execute(
        "INSERT INTO consent_artifacts(request_id, artifact_json, created_at) VALUES(?,?,?);",
        (rid, json.dumps(artifact, ensure_ascii=False), time.time()),
    )
