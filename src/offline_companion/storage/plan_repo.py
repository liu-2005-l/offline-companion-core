"""摘要：桌面执行计划的 SQLite 持久化访问层。"""

from __future__ import annotations

import json
import time
from typing import Any


def save_plan(conn: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """摘要：完整保存计划与步骤。

    参数：
        conn: SQLite 连接。
        plan: 前端计划 payload。
    返回值：
        保存后的计划 payload。
    """
    now = time.time()
    plan.setdefault("created_at", now)
    plan["updated_at"] = plan.get("updated_at") or now
    with conn:
        conn.execute(
            """
            INSERT INTO plans(plan_id, goal, status, created_at, updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(plan_id) DO UPDATE SET
                goal = excluded.goal,
                status = excluded.status,
                updated_at = excluded.updated_at;
            """,
            (
                str(plan["id"]),
                str(plan.get("goal") or ""),
                str(plan.get("status") or "pending"),
                float(plan["created_at"]),
                float(plan["updated_at"]),
            ),
        )
        conn.execute("DELETE FROM plan_steps WHERE plan_id = ?;", (str(plan["id"]),))
        for step in plan.get("steps", []):
            _insert_step(conn, str(plan["id"]), step, updated_at=float(plan["updated_at"]))
    return get_plan(conn, str(plan["id"])) or plan


def get_plan(conn: Any, plan_id: str) -> dict[str, Any] | None:
    """摘要：读取单个计划及其步骤。

    参数：
        conn: SQLite 连接。
        plan_id: 计划 ID。
    返回值：
        计划 payload；不存在时返回 None。
    """
    row = conn.execute("SELECT * FROM plans WHERE plan_id = ?;", (plan_id,)).fetchone()
    if row is None:
        return None
    steps = conn.execute(
        "SELECT * FROM plan_steps WHERE plan_id = ? ORDER BY step_id ASC;",
        (plan_id,),
    ).fetchall()
    return {
        "id": str(row["plan_id"]),
        "goal": str(row["goal"]),
        "status": str(row["status"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "steps": [_step_payload(step) for step in steps],
    }


def update_plan(conn: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """摘要：更新完整计划状态。

    参数：
        conn: SQLite 连接。
        plan: 计划 payload。
    返回值：
        更新后的计划 payload。
    """
    plan["updated_at"] = time.time()
    return save_plan(conn, plan)


def delete_plan(conn: Any, plan_id: str) -> None:
    """摘要：删除计划及步骤。

    参数：
        conn: SQLite 连接。
        plan_id: 计划 ID。
    """
    with conn:
        conn.execute("DELETE FROM plans WHERE plan_id = ?;", (plan_id,))


def _insert_step(conn: Any, plan_id: str, step: dict[str, Any], *, updated_at: float) -> None:
    conn.execute(
        """
        INSERT INTO plan_steps(
            plan_id, step_id, title, deps_json, risk, status, requires_auth,
            result, error, consent_request_id, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?);
        """,
        (
            plan_id,
            int(step["id"]),
            str(step.get("title") or ""),
            json.dumps(step.get("deps") or [], ensure_ascii=False),
            str(step.get("risk") or "low"),
            str(step.get("status") or "pending"),
            1 if bool(step.get("requires_auth", False)) else 0,
            step.get("result"),
            step.get("error"),
            step.get("consent_request_id"),
            updated_at,
        ),
    )


def _step_payload(row: Any) -> dict[str, Any]:
    payload = {
        "id": int(row["step_id"]),
        "title": str(row["title"]),
        "deps": _loads_list(row["deps_json"]),
        "risk": str(row["risk"]),
        "status": str(row["status"]),
        "requires_auth": bool(row["requires_auth"]),
        "result": row["result"],
        "error": row["error"],
    }
    if row["consent_request_id"]:
        payload["consent_request_id"] = str(row["consent_request_id"])
    return payload


def _loads_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
