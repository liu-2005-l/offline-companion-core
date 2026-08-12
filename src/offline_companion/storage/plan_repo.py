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
    _ensure_plan_columns(conn)
    plan.setdefault("created_at", now)
    plan["updated_at"] = plan.get("updated_at") or now
    with conn:
        conn.execute(
            """
            INSERT INTO plans(plan_id, goal, status, skill_name, skill_stages_json, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(plan_id) DO UPDATE SET
                goal = excluded.goal,
                status = excluded.status,
                skill_name = excluded.skill_name,
                skill_stages_json = excluded.skill_stages_json,
                updated_at = excluded.updated_at;
            """,
            (
                str(plan["id"]),
                str(plan.get("goal") or ""),
                str(plan.get("status") or "pending"),
                plan.get("skill_name"),
                json.dumps(plan.get("skill_stages") or [], ensure_ascii=False),
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
    _ensure_plan_columns(conn)
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
        "skill_name": row["skill_name"],
        "skill_stages": _loads_list(row["skill_stages_json"]),
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
            plan_id, step_id, title, description, expected_output, verification,
            completion_criteria, stage, estimated_minutes, files_json, deps_json,
            risk, status, requires_auth,
            result, error, consent_request_id, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
        """,
        (
            plan_id,
            int(step["id"]),
            str(step.get("title") or ""),
            str(step.get("description") or ""),
            str(step.get("expected_output") or ""),
            str(step.get("verification") or ""),
            str(step.get("completion_criteria") or ""),
            step.get("stage"),
            int(step.get("estimated_minutes") or 0),
            json.dumps(step.get("files") or [], ensure_ascii=False),
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
        "description": str(row["description"] or ""),
        "expected_output": str(row["expected_output"] or ""),
        "verification": str(row["verification"] or ""),
        "completion_criteria": str(row["completion_criteria"] or ""),
        "stage": row["stage"],
        "estimated_minutes": int(row["estimated_minutes"] or 0),
        "files": _loads_list(row["files_json"]),
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


def _ensure_plan_columns(conn: Any) -> None:
    """摘要：为旧 SQLite 文件补齐计划强类型字段列。"""
    plan_columns = _table_columns(conn, "plans")
    step_columns = _table_columns(conn, "plan_steps")
    with conn:
        if "skill_name" not in plan_columns:
            conn.execute("ALTER TABLE plans ADD COLUMN skill_name TEXT;")
        if "skill_stages_json" not in plan_columns:
            conn.execute("ALTER TABLE plans ADD COLUMN skill_stages_json TEXT NOT NULL DEFAULT '[]';")
        step_additions = {
            "description": "TEXT NOT NULL DEFAULT ''",
            "expected_output": "TEXT NOT NULL DEFAULT ''",
            "verification": "TEXT NOT NULL DEFAULT ''",
            "completion_criteria": "TEXT NOT NULL DEFAULT ''",
            "stage": "TEXT",
            "estimated_minutes": "INTEGER NOT NULL DEFAULT 0",
            "files_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column, definition in step_additions.items():
            if column not in step_columns:
                conn.execute(f"ALTER TABLE plan_steps ADD COLUMN {column} {definition};")


def _table_columns(conn: Any, table_name: str) -> set[str]:
    """摘要：读取 SQLite 表列名集合。"""
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name});").fetchall()}


def _loads_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
