"""GoalRepository：基于 goal 类型记忆的目标 CRUD。"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from threading import RLock
from typing import Any

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.shared.types import FeedbackLevel, Goal, GoalPriority, GoalStatus

_SOURCE = "user_explicit"
_MEMORY_TYPE = "goal"
_NEGATIVE_SCORE_THRESHOLD = 2.0
_FEEDBACK_WEIGHTS = {
    FeedbackLevel.STRONG_NEGATIVE.value: 1.0,
    FeedbackLevel.WEAK_NEGATIVE.value: 0.3,
    FeedbackLevel.POSITIVE.value: -0.2,
}


class GoalRepository:
    """摘要：创建目标时复用记忆链路，目标专属字段通过参数化 SQL 更新。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        memory_lifecycle: MemoryLifecycleManager | None = None,
    ) -> None:
        self._conn = conn
        self._memory_lifecycle = memory_lifecycle or MemoryLifecycleManager()
        self._lock = RLock()

    def create(
        self,
        description: str,
        *,
        priority: str = GoalPriority.NORMAL.value,
        deadline: float | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """摘要：创建非紧急长期目标并返回字符串 ID。"""
        normalized_description = str(description).strip()
        if not normalized_description:
            raise ValueError("goal description must not be empty")
        self._validate_priority(priority)
        if priority == GoalPriority.URGENT.value:
            raise ValueError("urgent priority can only be set via update_priority")
        normalized_deadline = None if deadline is None else float(deadline)
        normalized_tags = self._normalize_tags(tags or [])
        metadata = {
            "goal_status": GoalStatus.ACTIVE.value,
            "priority": priority,
            "progress": 0.0,
            "deadline": normalized_deadline,
            "reminder_count": 0,
            "last_reminder_at": None,
            "reminder_history": [],
            "negative_feedback_score": 0.0,
            "tags": normalized_tags,
        }
        with self._lock, self._conn:
            chunk_id = self._memory_lifecycle.add_memory_chunk(
                self._conn,
                normalized_description,
                session_id=None,
                source=_SOURCE,
                meta={
                    "content": normalized_description,
                    "memory_type": _MEMORY_TYPE,
                    "status": "active",
                    "metadata": metadata,
                },
            )
        return str(chunk_id)

    def get(self, goal_id: str) -> Goal | None:
        """摘要：按 ID 查询目标。"""
        row = self._conn.execute(
            "SELECT id, content, status, metadata, created_at, modified_at "
            "FROM memory_chunks WHERE id = ? AND memory_type = ?;",
            (self._goal_id(goal_id), _MEMORY_TYPE),
        ).fetchone()
        return None if row is None else self._row_to_goal(row)

    def list_active(self) -> list[Goal]:
        """摘要：按创建时间返回所有活动目标。"""
        rows = self._conn.execute(
            "SELECT id, content, status, metadata, created_at, modified_at "
            "FROM memory_chunks WHERE memory_type = ? AND status = 'active' "
            "ORDER BY created_at ASC, id ASC;",
            (_MEMORY_TYPE,),
        ).fetchall()
        goals = [self._row_to_goal(row) for row in rows]
        return [goal for goal in goals if goal.goal_status == GoalStatus.ACTIVE.value]

    def update_progress(self, goal_id: str, progress: float) -> None:
        """摘要：更新 0.0 至 1.0 的目标进度；完成时同步停用目标。"""
        normalized = float(progress)
        if not 0.0 <= normalized <= 1.0:
            raise ValueError(f"progress must be between 0.0 and 1.0, got {normalized}")
        if normalized == 1.0:
            self._mutate(goal_id, lambda metadata: metadata.update(progress=normalized, goal_status="completed"), db_status="cancelled")
            return
        self._mutate(goal_id, lambda metadata: metadata.update(progress=normalized))

    def update_priority(self, goal_id: str, priority: str) -> None:
        """摘要：更新目标优先级；本方法是设置 urgent 的唯一仓库入口。"""
        self._validate_priority(priority)
        self._mutate(goal_id, lambda metadata: metadata.update(priority=priority))

    def record_reminder(self, goal_id: str) -> None:
        """摘要：原子递增提醒次数，并追加最近七天的提醒历史。"""
        now = time.time()

        def update(metadata: dict[str, Any]) -> None:
            metadata["reminder_count"] = int(metadata.get("reminder_count", 0)) + 1
            metadata["last_reminder_at"] = now
            history = metadata.get("reminder_history", [])
            if not isinstance(history, list):
                history = []
            cutoff = now - 7 * 86400.0
            metadata["reminder_history"] = [
                float(timestamp)
                for timestamp in history
                if isinstance(timestamp, (int, float)) and float(timestamp) >= cutoff
            ] + [now]

        self._mutate(goal_id, update)

    def get_reminder_count_today(self, goal_id: str, now: float) -> int:
        """摘要：返回目标最近二十四小时内的精确提醒次数。"""
        row = self._conn.execute(
            "SELECT metadata FROM memory_chunks WHERE id = ? AND memory_type = ?;",
            (self._goal_id(goal_id), _MEMORY_TYPE),
        ).fetchone()
        if row is None:
            return 0
        history = self._decode_metadata(row["metadata"]).get("reminder_history", [])
        if not isinstance(history, list):
            return 0
        cutoff = float(now) - 86400.0
        return sum(
            1
            for timestamp in history
            if isinstance(timestamp, (int, float)) and cutoff <= float(timestamp) <= float(now)
        )

    def record_feedback(self, goal_id: str, level: str) -> None:
        """摘要：按反馈权重更新非负的累计负反馈分。"""
        weight = _FEEDBACK_WEIGHTS.get(level)
        if weight is None:
            raise ValueError(f"invalid feedback level: {level}")

        def update(metadata: dict[str, Any]) -> None:
            current = float(metadata.get("negative_feedback_score", 0.0))
            metadata["negative_feedback_score"] = max(0.0, current + weight)

        self._mutate(goal_id, update)

    def deactivate(self, goal_id: str, reason: str = GoalStatus.COMPLETED.value) -> None:
        """摘要：将目标业务状态设为完成或放弃，并将记忆状态设为 cancelled。"""
        if reason not in {GoalStatus.COMPLETED.value, GoalStatus.ABANDONED.value}:
            raise ValueError(f"invalid deactivate reason: {reason}")
        self._mutate(goal_id, lambda metadata: metadata.update(goal_status=reason), db_status="cancelled")

    def is_suppressed(self, goal_id: str) -> bool:
        """摘要：判断累计负反馈是否达到提醒抑制阈值。"""
        goal = self.get(goal_id)
        return goal is None or goal.negative_feedback_score >= _NEGATIVE_SCORE_THRESHOLD

    def _mutate(
        self,
        goal_id: str,
        mutation: Callable[[dict[str, Any]], None],
        *,
        db_status: str | None = None,
    ) -> None:
        """摘要：在仓库锁和单事务内完成 metadata 读改写。"""
        resolved_id = self._goal_id(goal_id)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT metadata FROM memory_chunks WHERE id = ? AND memory_type = ?;",
                (resolved_id, _MEMORY_TYPE),
            ).fetchone()
            if row is None:
                raise ValueError(f"goal not found: {goal_id}")
            metadata = self._decode_metadata(row["metadata"])
            mutation(metadata)
            now = time.time()
            if db_status is None:
                self._conn.execute(
                    "UPDATE memory_chunks SET metadata = ?, modified_at = ? "
                    "WHERE id = ? AND memory_type = ?;",
                    (json.dumps(metadata, ensure_ascii=False), now, resolved_id, _MEMORY_TYPE),
                )
            else:
                self._conn.execute(
                    "UPDATE memory_chunks SET metadata = ?, status = ?, modified_at = ? "
                    "WHERE id = ? AND memory_type = ?;",
                    (json.dumps(metadata, ensure_ascii=False), db_status, now, resolved_id, _MEMORY_TYPE),
                )

    @staticmethod
    def _row_to_goal(row: sqlite3.Row) -> Goal:
        metadata = GoalRepository._decode_metadata(row["metadata"])
        return Goal(
            goal_id=str(row["id"]),
            description=str(row["content"] or ""),
            goal_status=str(metadata.get("goal_status") or GoalStatus.ACTIVE.value),
            priority=str(metadata.get("priority") or GoalPriority.NORMAL.value),
            progress=float(metadata.get("progress", 0.0)),
            created_at=GoalRepository._timestamp(row["created_at"]),
            updated_at=GoalRepository._timestamp(row["modified_at"]),
            deadline=None if metadata.get("deadline") is None else float(metadata["deadline"]),
            reminder_count=int(metadata.get("reminder_count", 0)),
            last_reminder_at=(
                None if metadata.get("last_reminder_at") is None else float(metadata["last_reminder_at"])
            ),
            negative_feedback_score=float(metadata.get("negative_feedback_score", 0.0)),
            tags=GoalRepository._normalize_tags(metadata.get("tags", [])),
        )

    @staticmethod
    def _decode_metadata(value: object) -> dict[str, Any]:
        try:
            decoded = json.loads(value) if isinstance(value, str) and value else {}
        except (json.JSONDecodeError, TypeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _timestamp(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _goal_id(goal_id: str) -> int:
        try:
            return int(goal_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid goal id: {goal_id}") from exc

    @staticmethod
    def _validate_priority(priority: str) -> None:
        if priority not in {item.value for item in GoalPriority}:
            raise ValueError(f"invalid priority: {priority}")

    @staticmethod
    def _normalize_tags(tags: object) -> list[str]:
        if not isinstance(tags, (list, tuple)):
            return []
        return list(dict.fromkeys(str(tag).strip() for tag in tags if str(tag).strip()))
