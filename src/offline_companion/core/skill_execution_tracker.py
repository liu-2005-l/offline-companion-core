"""skill_execution_tracker：持久化 Skill 阶段执行状态与证据。"""

from __future__ import annotations

import sqlite3
import uuid
from threading import RLock
from time import time

_VALID_STATUSES = frozenset({"executing", "completed", "failed"})


class SkillExecutionTracker:
    """摘要：在 companion SQLite 中跟踪会话级 Skill 阶段状态。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = RLock()
        self._init_table()

    def _init_table(self) -> None:
        """摘要：幂等创建阶段执行表及会话查询索引。"""
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_executions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'executing',
                    evidence TEXT,
                    started_at REAL NOT NULL,
                    completed_at REAL,
                    UNIQUE(session_id, skill_name, stage)
                );
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_skill_exec_session "
                "ON skill_executions(session_id, skill_name);"
            )

    def start_stage(self, session_id: str, skill_name: str, stage: str) -> dict[str, object]:
        """摘要：开始阶段；已完成阶段不可重新开始。"""
        self._validate_identity(session_id, skill_name, stage)
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT id, status FROM skill_executions "
                "WHERE session_id = ? AND skill_name = ? AND stage = ?;",
                (session_id, skill_name, stage),
            ).fetchone()
            if existing is not None:
                if existing[1] == "completed":
                    return {"ok": False, "error": "stage_already_completed", "execution_id": existing[0]}
                return {"ok": True, "execution_id": existing[0], "status": existing[1]}
            execution_id = uuid.uuid4().hex
            self._conn.execute(
                "INSERT INTO skill_executions "
                "(id, session_id, skill_name, stage, status, started_at) "
                "VALUES (?, ?, ?, ?, 'executing', ?);",
                (execution_id, session_id, skill_name, stage, time()),
            )
        return {"ok": True, "execution_id": execution_id, "status": "executing"}

    def complete_stage(
        self,
        session_id: str,
        skill_name: str,
        stage: str,
        evidence: str | None = None,
    ) -> dict[str, object]:
        """摘要：将已开始阶段标记完成并保存验证证据。"""
        return self._finish_stage(session_id, skill_name, stage, "completed", evidence)

    def fail_stage(
        self,
        session_id: str,
        skill_name: str,
        stage: str,
        reason: str | None = None,
    ) -> dict[str, object]:
        """摘要：将已开始阶段标记失败并保存失败原因。"""
        return self._finish_stage(session_id, skill_name, stage, "failed", reason)

    def check_prerequisite(self, session_id: str, skill_name: str, prerequisite: str) -> bool:
        """摘要：检查指定前置阶段是否已完成。"""
        row = self._conn.execute(
            "SELECT status FROM skill_executions "
            "WHERE session_id = ? AND skill_name = ? AND stage = ?;",
            (session_id, skill_name, prerequisite),
        ).fetchone()
        return row is not None and row[0] == "completed"

    def get_progress(self, session_id: str, skill_name: str) -> list[dict[str, object]]:
        """摘要：按开始时间返回会话中某技能的阶段进度。"""
        rows = self._conn.execute(
            "SELECT stage, status, evidence, started_at, completed_at "
            "FROM skill_executions WHERE session_id = ? AND skill_name = ? "
            "ORDER BY started_at, stage;",
            (session_id, skill_name),
        ).fetchall()
        return [
            {
                "stage": row[0],
                "status": row[1],
                "evidence": row[2],
                "started_at": row[3],
                "completed_at": row[4],
            }
            for row in rows
        ]

    def _finish_stage(
        self,
        session_id: str,
        skill_name: str,
        stage: str,
        status: str,
        evidence: str | None,
    ) -> dict[str, object]:
        """摘要：仅允许已开始且尚未终结的阶段进入终态。"""
        self._validate_identity(session_id, skill_name, stage)
        if status not in _VALID_STATUSES - {"executing"}:
            raise ValueError(f"invalid skill execution status: {status}")
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE skill_executions SET status = ?, evidence = ?, completed_at = ? "
                "WHERE session_id = ? AND skill_name = ? AND stage = ? AND status = 'executing';",
                (status, evidence, time(), session_id, skill_name, stage),
            )
            if cursor.rowcount != 1:
                return {"ok": False, "error": "stage_not_executing", "stage": stage}
        return {"ok": True, "stage": stage, "status": status}

    @staticmethod
    def _validate_identity(session_id: str, skill_name: str, stage: str) -> None:
        if not session_id or not skill_name or not stage:
            raise ValueError("session_id, skill_name and stage must be non-empty")
