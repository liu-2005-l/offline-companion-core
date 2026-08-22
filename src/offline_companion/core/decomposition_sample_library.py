"""decomposition_sample_library：任务拆解样本的本地存储与生命周期。"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from difflib import SequenceMatcher
from enum import Enum
from threading import RLock
from typing import Any

from offline_companion.core.event_stream import EventStream
from offline_companion.core.memory_lifecycle.embedding import maybe_write_embedding
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.shared.deterministic_embedding import (
    cosine_similarity,
    embed_text,
    tokenize_for_embedding,
)

SAMPLE_MEMORY_TYPE = "decomposition_sample"
PLANSTEP_SCHEMA_VERSION = 1
SAMPLE_SIMILARITY_MIN = 0.35
SAMPLE_SIMILARITY_REUSE = 0.98
SAMPLE_MERGE_SIMILARITY = 0.95
SAMPLE_TOP_K = 2
SAMPLE_TOKEN_BUDGET = 1000
SAMPLE_TOKEN_BUDGET_PER_ITEM = 400
_SAMPLE_SOURCE = "plan_decomposer"
_STEP_FIELDS = (
    "title",
    "description",
    "expected_output",
    "verification",
    "completion_criteria",
    "stage",
    "subagent_type",
)

logger = logging.getLogger(__name__)


class SampleState(str, Enum):
    """摘要：拆解样本业务状态。"""

    CANDIDATE = "candidate"
    VERIFIED = "verified"
    STALE = "stale"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class VerifyKind(str, Enum):
    """摘要：样本验证来源。"""

    USER = "user"
    AUTO = "auto"


class InvalidSampleTransitionError(ValueError):
    """摘要：样本状态迁移不符合用户主权规则。"""


@dataclass(frozen=True)
class DecompositionSample:
    """摘要：从 memory_chunks 恢复的强类型拆解样本。"""

    sample_id: str
    task_description: str
    sample_state: str
    verify_kind: str | None
    steps: tuple[dict[str, Any], ...]
    schema_version: int
    source: str
    plan_id: str | None
    provenance_sample_ids: tuple[str, ...]
    usage: dict[str, Any]
    tool_refs: tuple[str, ...]
    content_hash: str
    version: int
    status: str
    created_at: float
    updated_at: float
    stale_reason: str | None = None
    rejected_by: str | None = None
    last_actor: str | None = None


@dataclass(frozen=True)
class SampleShot:
    """摘要：经过检索、裁剪并可安全注入拆解器的单条范例。"""

    sample_id: str
    task_description: str
    steps: tuple[dict[str, str], ...]
    similarity: float
    score: float
    tool_refs: tuple[str, ...]
    token_count: int


class SampleRepository:
    """摘要：复用 memory_chunks 保存拆解样本并提供参数化 CRUD。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        memory_lifecycle: MemoryLifecycleManager | None = None,
    ) -> None:
        """摘要：初始化样本仓储。

        参数：
            conn: 已初始化 memory_chunks 的 SQLite 连接。
            memory_lifecycle: 可选记忆生命周期入口，缺省时使用默认实现。
        """
        self._conn = conn
        self._memory_lifecycle = memory_lifecycle or MemoryLifecycleManager()
        self._lock = RLock()
        self._has_updated_at = "updated_at" in {
            str(row[1]) for row in self._conn.execute("PRAGMA table_info(memory_chunks);").fetchall()
        }

    def create_candidate(
        self,
        task_description: str,
        steps: Iterable[object],
        *,
        source: str,
        plan_id: str | None = None,
        provenance_sample_ids: Iterable[str] = (),
        tool_refs: Iterable[str] | None = None,
    ) -> DecompositionSample:
        """摘要：创建 candidate 样本并返回完整记录。"""
        description = self._normalize_description(task_description)
        raw_steps = list(steps)
        serialized_steps = self.serialize_steps(raw_steps)
        if not serialized_steps:
            raise ValueError("decomposition sample steps must not be empty")
        normalized_source = str(source).strip()
        if normalized_source not in {"llm", "rule", "user_edit"}:
            raise ValueError(f"invalid decomposition sample source: {source}")
        normalized_provenance = self._normalize_strings(provenance_sample_ids)
        normalized_tools = self._normalize_strings(
            self.extract_tool_refs(raw_steps) if tool_refs is None else tool_refs
        )
        content_hash = self.content_hash(description, serialized_steps)
        with self._lock:
            duplicate, similarity = self._find_duplicate(description, serialized_steps, content_hash)
            if duplicate is not None:
                return self._merge_duplicate(duplicate.sample_id, similarity=similarity)
            metadata = {
                "sample_state": SampleState.CANDIDATE.value,
                "verify_kind": None,
                "steps": serialized_steps,
                "schema_version": PLANSTEP_SCHEMA_VERSION,
                "source": normalized_source,
                "plan_id": str(plan_id).strip() if plan_id else None,
                "provenance": {"sample_ids": normalized_provenance},
                "usage": self.empty_usage(),
                "tool_refs": normalized_tools,
                "content_hash": content_hash,
                "version": 1,
                "stale_reason": None,
                "rejected_by": None,
                "last_actor": "system",
            }
            with self._conn:
                sample_id = self._memory_lifecycle.add_memory_chunk(
                    self._conn,
                    description,
                    session_id=None,
                    source=_SAMPLE_SOURCE,
                    meta={
                        "content": description,
                        "memory_type": SAMPLE_MEMORY_TYPE,
                        "status": "active",
                        "metadata": metadata,
                    },
                )
        created = self.get(str(sample_id))
        if created is None:
            raise RuntimeError("created decomposition sample could not be reloaded")
        return created

    def _find_duplicate(
        self,
        task_description: str,
        steps: list[dict[str, Any]],
        content_hash: str,
    ) -> tuple[DecompositionSample | None, float]:
        """摘要：在任意业务状态中查找 exact 或大于 0.95 的近重复样本。"""
        exact_row = self._conn.execute(
            "SELECT id, content, status, metadata, created_at, modified_at "
            "FROM memory_chunks WHERE memory_type = ? "
            "AND json_extract(metadata, '$.content_hash') = ? "
            "ORDER BY modified_at DESC, id DESC LIMIT 1;",
            (SAMPLE_MEMORY_TYPE, content_hash),
        ).fetchone()
        if exact_row is not None:
            return self._row_to_sample(exact_row), 1.0
        target_tokens = self._content_tokens(task_description, steps)
        if not target_tokens:
            return None, 0.0
        rows = self._conn.execute(
            "SELECT id, content, status, metadata, created_at, modified_at "
            "FROM memory_chunks WHERE memory_type = ? ORDER BY modified_at DESC, id DESC;",
            (SAMPLE_MEMORY_TYPE,),
        ).fetchall()
        best_sample: DecompositionSample | None = None
        best_similarity = 0.0
        for row in rows:
            sample = self._row_to_sample(row)
            similarity = SequenceMatcher(
                None,
                target_tokens,
                self._content_tokens(sample.task_description, sample.steps),
                autojunk=False,
            ).ratio()
            if similarity > best_similarity:
                best_sample = sample
                best_similarity = similarity
        if best_similarity > SAMPLE_MERGE_SIMILARITY:
            return best_sample, best_similarity
        return None, 0.0

    def _merge_duplicate(self, sample_id: str, *, similarity: float) -> DecompositionSample:
        """摘要：以单条参数化 UPDATE 原子累加重复生成的相似度统计。"""
        resolved_id = self._sample_id(sample_id)
        now = time.time()
        assignments = [
            (
                "metadata = json_set(metadata, "
                "'$.usage.similarity_sum', "
                "COALESCE(json_extract(metadata, '$.usage.similarity_sum'), 0) + ?, "
                "'$.usage.similarity_count', "
                "COALESCE(json_extract(metadata, '$.usage.similarity_count'), 0) + 1)"
            ),
            "modified_at = ?",
        ]
        parameters: list[Any] = [float(similarity), now]
        if self._has_updated_at:
            assignments.append("updated_at = ?")
            parameters.append(now)
        parameters.extend((resolved_id, SAMPLE_MEMORY_TYPE))
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"UPDATE memory_chunks SET {', '.join(assignments)} "
                "WHERE id = ? AND memory_type = ?;",
                tuple(parameters),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"decomposition sample not found: {sample_id}")
        merged = self.get(sample_id)
        if merged is None:
            raise RuntimeError("merged decomposition sample could not be reloaded")
        return merged

    def get(self, sample_id: str) -> DecompositionSample | None:
        """摘要：按 ID 获取单条拆解样本。"""
        row = self._conn.execute(
            "SELECT id, content, status, metadata, created_at, modified_at "
            "FROM memory_chunks WHERE id = ? AND memory_type = ?;",
            (self._sample_id(sample_id), SAMPLE_MEMORY_TYPE),
        ).fetchone()
        return None if row is None else self._row_to_sample(row)

    def delete(self, sample_id: str) -> bool:
        """摘要：永久删除单条拆解样本，不保留业务状态或追加事件。"""
        resolved_id = self._sample_id(sample_id)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM memory_chunks WHERE id = ? AND memory_type = ?;",
                (resolved_id, SAMPLE_MEMORY_TYPE),
            )
        return cursor.rowcount == 1

    def list_samples(
        self,
        *,
        sample_state: str | None = None,
        sample_states: Iterable[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DecompositionSample]:
        """摘要：按更新时间倒序分页列出样本，业务状态过滤全部在 SQLite 完成。"""
        normalized_limit = max(1, min(int(limit), 500))
        normalized_offset = max(0, int(offset))
        states = self._normalize_sample_states(sample_state, sample_states)
        state_sql, state_params = self._state_filter_sql(states)
        rows = self._conn.execute(
            "SELECT id, content, status, metadata, created_at, modified_at "
            "FROM memory_chunks WHERE memory_type = ? "
            f"{state_sql} ORDER BY modified_at DESC, id DESC LIMIT ? OFFSET ?;",
            (SAMPLE_MEMORY_TYPE, *state_params, normalized_limit, normalized_offset),
        ).fetchall()
        return [self._row_to_sample(row) for row in rows]

    def count_samples(
        self,
        *,
        sample_state: str | None = None,
        sample_states: Iterable[str] | None = None,
    ) -> int:
        """摘要：在 SQLite 内统计指定业务状态的样本总数。"""
        states = self._normalize_sample_states(sample_state, sample_states)
        state_sql, state_params = self._state_filter_sql(states)
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM memory_chunks WHERE memory_type = ? "
            f"{state_sql};",
            (SAMPLE_MEMORY_TYPE, *state_params),
        ).fetchone()
        return int(row["count"] if row is not None else 0)

    @classmethod
    def _normalize_sample_states(
        cls,
        sample_state: str | None,
        sample_states: Iterable[str] | None,
    ) -> tuple[str, ...]:
        if sample_state is not None and sample_states is not None:
            raise ValueError("sample_state and sample_states are mutually exclusive")
        if sample_state is not None:
            cls.validate_state(sample_state)
            return (sample_state,)
        normalized = tuple(dict.fromkeys(str(state).strip() for state in sample_states or ()))
        for state in normalized:
            cls.validate_state(state)
        return normalized

    @staticmethod
    def _state_filter_sql(states: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        if not states:
            return "", ()
        placeholders = ", ".join("?" for _ in states)
        return (
            (
                "AND COALESCE(json_extract(metadata, '$.sample_state'), 'candidate') "
                f"IN ({placeholders}) "
            ),
            states,
        )

    def mutate_metadata(
        self,
        sample_id: str,
        mutation: Callable[[dict[str, Any]], None],
        *,
        db_status: str | None = None,
    ) -> DecompositionSample:
        """摘要：在单事务内参数化更新样本 metadata。"""
        resolved_id = self._sample_id(sample_id)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT metadata, status FROM memory_chunks WHERE id = ? AND memory_type = ?;",
                (resolved_id, SAMPLE_MEMORY_TYPE),
            ).fetchone()
            if row is None:
                raise ValueError(f"decomposition sample not found: {sample_id}")
            metadata = self.decode_metadata(row["metadata"])
            mutation(metadata)
            status = str(db_status or row["status"] or "active")
            if status not in {"active", "cancelled"}:
                raise ValueError(f"invalid decomposition sample db status: {status}")
            now = time.time()
            if self._has_updated_at:
                self._conn.execute(
                    "UPDATE memory_chunks SET metadata = ?, status = ?, modified_at = ?, updated_at = ? "
                    "WHERE id = ? AND memory_type = ?;",
                    (
                        json.dumps(metadata, ensure_ascii=False),
                        status,
                        now,
                        now,
                        resolved_id,
                        SAMPLE_MEMORY_TYPE,
                    ),
                )
            else:
                self._conn.execute(
                    "UPDATE memory_chunks SET metadata = ?, status = ?, modified_at = ? "
                    "WHERE id = ? AND memory_type = ?;",
                    (
                        json.dumps(metadata, ensure_ascii=False),
                        status,
                        now,
                        resolved_id,
                        SAMPLE_MEMORY_TYPE,
                    ),
                )
        updated = self.get(str(resolved_id))
        if updated is None:
            raise RuntimeError("updated decomposition sample could not be reloaded")
        return updated

    def assign_plan_id(self, sample_id: str, plan_id: str) -> DecompositionSample:
        """摘要：在计划 ID 分配后回填候选样本血缘。"""
        normalized_plan_id = str(plan_id).strip()
        if not normalized_plan_id:
            raise ValueError("decomposition sample plan_id must not be empty")

        def mutation(metadata: dict[str, Any]) -> None:
            metadata["plan_id"] = normalized_plan_id

        return self.mutate_metadata(sample_id, mutation)

    def record_injection(
        self,
        sample_id: str,
        *,
        hit_at: float | None = None,
        similarity: float | None = None,
    ) -> DecompositionSample:
        """摘要：原子记录样本被注入一次及最后命中时间。"""
        resolved_hit_at = float(time.time() if hit_at is None else hit_at)

        def mutation(metadata: dict[str, Any]) -> None:
            usage = metadata.get("usage")
            normalized_usage = dict(usage) if isinstance(usage, dict) else self.empty_usage()
            normalized_usage["injected_count"] = int(normalized_usage.get("injected_count") or 0) + 1
            normalized_usage["last_hit_at"] = resolved_hit_at
            normalized_usage["last_injected_at"] = resolved_hit_at
            if similarity is not None:
                normalized_usage["similarity_sum"] = float(
                    normalized_usage.get("similarity_sum") or 0.0
                ) + float(similarity)
                normalized_usage["similarity_count"] = int(
                    normalized_usage.get("similarity_count") or 0
                ) + 1
            metadata["usage"] = normalized_usage

        return self.mutate_metadata(sample_id, mutation)

    def record_plan_outcome(self, sample_id: str, *, completed: bool) -> DecompositionSample:
        """摘要：原子累计一次 provenance 计划结果并维护连续失败次数。"""

        def mutation(metadata: dict[str, Any]) -> None:
            usage = metadata.get("usage")
            normalized_usage = dict(usage) if isinstance(usage, dict) else self.empty_usage()
            if completed:
                normalized_usage["plan_completed"] = int(normalized_usage.get("plan_completed") or 0) + 1
                normalized_usage["consecutive_failures"] = 0
            else:
                normalized_usage["plan_failed"] = int(normalized_usage.get("plan_failed") or 0) + 1
                normalized_usage["consecutive_failures"] = int(
                    normalized_usage.get("consecutive_failures") or 0
                ) + 1
            metadata["usage"] = normalized_usage

        return self.mutate_metadata(sample_id, mutation)

    def edit_content(
        self,
        sample_id: str,
        task_description: str,
        steps: Iterable[object],
        mutation: Callable[[dict[str, Any], list[dict[str, Any]]], None],
    ) -> DecompositionSample:
        """摘要：原子更新任务描述、步骤和相关 metadata。"""
        resolved_id = self._sample_id(sample_id)
        description = self._normalize_description(task_description)
        serialized_steps = self.serialize_steps(steps)
        if not serialized_steps:
            raise ValueError("decomposition sample steps must not be empty")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT metadata FROM memory_chunks WHERE id = ? AND memory_type = ?;",
                (resolved_id, SAMPLE_MEMORY_TYPE),
            ).fetchone()
            if row is None:
                raise ValueError(f"decomposition sample not found: {sample_id}")
            metadata = self.decode_metadata(row["metadata"])
            mutation(metadata, serialized_steps)
            now = time.time()
            if self._has_updated_at:
                self._conn.execute(
                    "UPDATE memory_chunks SET content = ?, body = ?, metadata = ?, status = 'active', "
                    "modified_at = ?, updated_at = ? WHERE id = ? AND memory_type = ?;",
                    (
                        description,
                        description,
                        json.dumps(metadata, ensure_ascii=False),
                        now,
                        now,
                        resolved_id,
                        SAMPLE_MEMORY_TYPE,
                    ),
                )
            else:
                self._conn.execute(
                    "UPDATE memory_chunks SET content = ?, body = ?, metadata = ?, status = 'active', "
                    "modified_at = ? WHERE id = ? AND memory_type = ?;",
                    (
                        description,
                        description,
                        json.dumps(metadata, ensure_ascii=False),
                        now,
                        resolved_id,
                        SAMPLE_MEMORY_TYPE,
                    ),
                )
            maybe_write_embedding(self._conn, resolved_id, description)
        updated = self.get(str(resolved_id))
        if updated is None:
            raise RuntimeError("edited decomposition sample could not be reloaded")
        return updated

    @staticmethod
    def serialize_steps(steps: Iterable[object]) -> list[dict[str, Any]]:
        """摘要：仅保留 few-shot 有价值且不含文件路径的七个字段。"""
        serialized: list[dict[str, Any]] = []
        for raw_step in steps:
            if is_dataclass(raw_step):
                payload = asdict(raw_step)
            elif isinstance(raw_step, Mapping):
                payload = dict(raw_step)
            else:
                payload = vars(raw_step) if hasattr(raw_step, "__dict__") else {}
            item: dict[str, Any] = {}
            for field_name in _STEP_FIELDS:
                value = payload.get(field_name)
                if isinstance(value, Enum):
                    value = value.value
                item[field_name] = None if value is None else str(value).strip()
            if not item["title"]:
                item["title"] = str(payload.get("step_id") or "").strip()
            if not item["description"]:
                nested_payload = payload.get("payload")
                if isinstance(nested_payload, Mapping):
                    item["description"] = str(nested_payload.get("description") or "").strip()
            if not item["title"] or not item["description"]:
                raise ValueError("decomposition sample step requires title and description")
            serialized.append(item)
        return serialized

    @staticmethod
    def extract_tool_refs(steps: Iterable[object]) -> list[str]:
        """摘要：从 action、tool 或 skill_id 前缀提取工具引用。"""
        refs: list[str] = []
        for raw_step in steps:
            payload = asdict(raw_step) if is_dataclass(raw_step) else dict(raw_step) if isinstance(raw_step, Mapping) else vars(raw_step)
            raw_ref = payload.get("action") or payload.get("tool") or payload.get("skill_id")
            if not raw_ref:
                continue
            normalized = str(raw_ref).strip().split(":", 1)[0].split(".", 1)[0]
            if normalized and normalized != "chat":
                refs.append(normalized)
        return list(dict.fromkeys(refs))

    @staticmethod
    def content_hash(task_description: str, steps: Iterable[Mapping[str, Any]]) -> str:
        """摘要：计算任务描述和步骤内容的稳定哈希。"""
        payload = {
            "task_description": str(task_description).strip(),
            "steps": [dict(step) for step in steps],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _content_tokens(
        task_description: str,
        steps: Iterable[Mapping[str, Any]],
    ) -> list[str]:
        payload = [str(task_description).strip()]
        for step in steps:
            payload.extend(str(step.get(field_name) or "").strip() for field_name in _STEP_FIELDS)
        return tokenize_for_embedding("\n".join(payload))

    @staticmethod
    def empty_usage() -> dict[str, Any]:
        """摘要：返回新样本的空使用统计。"""
        return {
            "injected_count": 0,
            "last_hit_at": None,
            "last_injected_at": None,
            "similarity_sum": 0.0,
            "similarity_count": 0,
            "plan_completed": 0,
            "plan_failed": 0,
            "consecutive_failures": 0,
        }

    @staticmethod
    def validate_state(sample_state: str) -> None:
        """摘要：校验业务状态值。"""
        if sample_state not in {item.value for item in SampleState}:
            raise ValueError(f"invalid decomposition sample state: {sample_state}")

    @staticmethod
    def decode_metadata(value: object) -> dict[str, Any]:
        """摘要：安全解析 metadata JSON。"""
        try:
            decoded = json.loads(value) if isinstance(value, str) and value else {}
        except (json.JSONDecodeError, TypeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _normalize_description(value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("decomposition sample task description must not be empty")
        return normalized

    @staticmethod
    def _normalize_strings(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

    @staticmethod
    def _sample_id(sample_id: str) -> int:
        try:
            return int(sample_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid decomposition sample id: {sample_id}") from exc

    @staticmethod
    def _row_to_sample(row: sqlite3.Row) -> DecompositionSample:
        metadata = SampleRepository.decode_metadata(row["metadata"])
        provenance = metadata.get("provenance")
        usage = metadata.get("usage")
        steps = metadata.get("steps")
        return DecompositionSample(
            sample_id=str(row["id"]),
            task_description=str(row["content"] or ""),
            sample_state=str(metadata.get("sample_state") or SampleState.CANDIDATE.value),
            verify_kind=str(metadata["verify_kind"]) if metadata.get("verify_kind") else None,
            steps=tuple(dict(item) for item in steps if isinstance(item, dict)) if isinstance(steps, list) else (),
            schema_version=int(metadata.get("schema_version") or 0),
            source=str(metadata.get("source") or "rule"),
            plan_id=str(metadata["plan_id"]) if metadata.get("plan_id") else None,
            provenance_sample_ids=(
                tuple(str(item) for item in provenance.get("sample_ids", []) if str(item).strip())
                if isinstance(provenance, dict)
                else ()
            ),
            usage=dict(usage) if isinstance(usage, dict) else SampleRepository.empty_usage(),
            tool_refs=tuple(str(item) for item in metadata.get("tool_refs", []) if str(item).strip()),
            content_hash=str(metadata.get("content_hash") or ""),
            version=max(1, int(metadata.get("version") or 1)),
            status=str(row["status"] or "active"),
            created_at=float(row["created_at"] or 0.0),
            updated_at=float(row["modified_at"] or 0.0),
            stale_reason=str(metadata["stale_reason"]) if metadata.get("stale_reason") else None,
            rejected_by=str(metadata["rejected_by"]) if metadata.get("rejected_by") else None,
            last_actor=str(metadata["last_actor"]) if metadata.get("last_actor") else None,
        )


class SampleLifecycleManager:
    """摘要：执行样本状态迁移并保证用户信号不被自动覆盖。"""

    def __init__(self, repository: SampleRepository, event_stream: EventStream | None = None) -> None:
        """摘要：初始化生命周期管理器。"""
        self._repository = repository
        self._event_stream = event_stream

    def create_candidate(self, *args: Any, **kwargs: Any) -> DecompositionSample:
        """摘要：创建 candidate 并发布留档事件。"""
        sample = self._repository.create_candidate(*args, **kwargs)
        if int(sample.usage.get("similarity_count") or 0) > 0:
            return sample
        self._emit(
            "sample/created",
            {
                "sample_id": sample.sample_id,
                "plan_id": sample.plan_id,
                "source": sample.source,
                "provenance": {"sample_ids": list(sample.provenance_sample_ids)},
            },
        )
        return sample

    def assign_plan_id(self, sample_id: str, plan_id: str) -> DecompositionSample:
        """摘要：在计划落库时补齐候选样本的计划血缘。"""
        return self._repository.assign_plan_id(sample_id, plan_id)

    def record_plan_outcome(self, sample_id: str, *, completed: bool) -> DecompositionSample:
        """摘要：记录 provenance 结果，并在连续三次失败时自动降为 stale。"""
        updated = self._repository.record_plan_outcome(sample_id, completed=completed)
        if completed:
            return updated
        consecutive_failures = int(updated.usage.get("consecutive_failures") or 0)
        injected_count = int(updated.usage.get("injected_count") or 0)
        auto_verified = (
            updated.sample_state == SampleState.VERIFIED.value
            and updated.verify_kind == VerifyKind.AUTO.value
        )
        if injected_count >= 3 and consecutive_failures >= 3 and (
            updated.sample_state == SampleState.CANDIDATE.value or auto_verified
        ):
            return self.mark_stale(updated.sample_id, reason="consecutive_failure")
        return updated

    def auto_verify_candidate(self, sample_id: str) -> DecompositionSample:
        """摘要：仅当候选样本累计两次成功计划后自动验证。"""
        current = self._require_sample(sample_id)
        if current.sample_state != SampleState.CANDIDATE.value:
            return current
        if int(current.usage.get("plan_completed") or 0) < 2:
            return current
        return self.auto_verify(sample_id, reason="plan_all_green")

    def confirm(self, sample_id: str, *, actor: str = "user") -> DecompositionSample:
        """摘要：由用户将任意非 user_verified 样本确认为最高权重范例。"""
        self._require_actor(actor, expected="user")
        current = self._require_sample(sample_id)
        if current.sample_state == SampleState.VERIFIED.value and current.verify_kind == VerifyKind.USER.value:
            return current
        return self._transition(
            current,
            SampleState.VERIFIED,
            actor=actor,
            event_type="sample/verified",
            verify_kind=VerifyKind.USER,
        )

    def auto_verify(self, sample_id: str, *, reason: str) -> DecompositionSample:
        """摘要：将全绿 candidate 自动升级为低权重 verified。"""
        current = self._require_sample(sample_id)
        if current.sample_state != SampleState.CANDIDATE.value:
            raise InvalidSampleTransitionError(
                f"cannot auto verify sample from {current.sample_state}"
            )
        return self._transition(
            current,
            SampleState.VERIFIED,
            actor="auto",
            reason=reason,
            event_type="sample/verified",
            verify_kind=VerifyKind.AUTO,
        )

    def edit(
        self,
        sample_id: str,
        *,
        task_description: str,
        steps: Iterable[object],
        actor: str = "user",
    ) -> DecompositionSample:
        """摘要：用户编辑任意样本并重置统计，结果直接成为 user_verified。"""
        self._require_actor(actor, expected="user")
        current = self._require_sample(sample_id)

        def mutation(metadata: dict[str, Any], serialized_steps: list[dict[str, Any]]) -> None:
            metadata.update(
                sample_state=SampleState.VERIFIED.value,
                verify_kind=VerifyKind.USER.value,
                steps=serialized_steps,
                schema_version=PLANSTEP_SCHEMA_VERSION,
                source="user_edit",
                usage=SampleRepository.empty_usage(),
                content_hash=SampleRepository.content_hash(task_description, serialized_steps),
                version=int(metadata.get("version") or current.version) + 1,
                stale_reason=None,
                rejected_by=None,
                last_actor=actor,
            )

        updated = self._repository.edit_content(sample_id, task_description, steps, mutation)
        self._emit_transition("sample/verified", current, updated, actor=actor, reason="user_edit")
        return updated

    def reject(self, sample_id: str, *, actor: str = "user") -> DecompositionSample:
        """摘要：用户丢弃样本，自动流程无权执行此迁移。"""
        self._require_actor(actor, expected="user")
        current = self._require_sample(sample_id)
        if current.sample_state == SampleState.REJECTED.value:
            raise InvalidSampleTransitionError("sample is already rejected")
        return self._transition(
            current,
            SampleState.REJECTED,
            actor=actor,
            event_type="sample/rejected",
        )

    def restore(self, sample_id: str, *, actor: str = "user") -> DecompositionSample:
        """摘要：用户将 rejected、archived 或 stale 样本恢复为 candidate。"""
        self._require_actor(actor, expected="user")
        current = self._require_sample(sample_id)
        if current.sample_state not in {
            SampleState.REJECTED.value,
            SampleState.ARCHIVED.value,
            SampleState.STALE.value,
        }:
            raise InvalidSampleTransitionError(
                f"cannot restore sample from {current.sample_state}"
            )
        return self._transition(
            current,
            SampleState.CANDIDATE,
            actor=actor,
            event_type="sample/restored",
        )

    def mark_stale(self, sample_id: str, *, reason: str, actor: str = "auto") -> DecompositionSample:
        """摘要：自动信号仅可将 candidate 或 auto_verified 降为 stale。"""
        self._require_actor(actor, expected="auto")
        normalized_reason = self._require_reason(reason)
        current = self._require_sample(sample_id)
        auto_verified = (
            current.sample_state == SampleState.VERIFIED.value
            and current.verify_kind == VerifyKind.AUTO.value
        )
        if current.sample_state != SampleState.CANDIDATE.value and not auto_verified:
            raise InvalidSampleTransitionError(
                f"automatic stale cannot override {current.sample_state}/{current.verify_kind}"
            )
        return self._transition(
            current,
            SampleState.STALE,
            actor=actor,
            reason=normalized_reason,
            event_type="sample/staled",
        )

    def archive(self, sample_id: str, *, reason: str, actor: str = "auto") -> DecompositionSample:
        """摘要：自动冷治理可归档非用户权威样本。"""
        if str(actor).strip() not in {"auto", "system"}:
            raise InvalidSampleTransitionError("transition requires actor=auto or system")
        normalized_reason = self._require_reason(reason)
        current = self._require_sample(sample_id)
        if current.sample_state in {SampleState.REJECTED.value, SampleState.ARCHIVED.value}:
            raise InvalidSampleTransitionError(f"cannot archive sample from {current.sample_state}")
        if current.sample_state == SampleState.VERIFIED.value and current.verify_kind == VerifyKind.USER.value:
            raise InvalidSampleTransitionError("automatic archive cannot override user_verified")
        return self._transition(
            current,
            SampleState.ARCHIVED,
            actor=actor,
            reason=normalized_reason,
            event_type="sample/archived",
        )

    def _transition(
        self,
        current: DecompositionSample,
        target: SampleState,
        *,
        actor: str,
        event_type: str | None = None,
        reason: str | None = None,
        verify_kind: VerifyKind | None = None,
    ) -> DecompositionSample:
        def mutation(metadata: dict[str, Any]) -> None:
            metadata["sample_state"] = target.value
            metadata["verify_kind"] = verify_kind.value if target is SampleState.VERIFIED and verify_kind else None
            metadata["stale_reason"] = reason if target is SampleState.STALE else None
            metadata["rejected_by"] = actor if target is SampleState.REJECTED else None
            metadata["last_actor"] = actor

        db_status = "cancelled" if target is SampleState.ARCHIVED else "active"
        updated = self._repository.mutate_metadata(current.sample_id, mutation, db_status=db_status)
        if event_type:
            self._emit_transition(event_type, current, updated, actor=actor, reason=reason)
        return updated

    def _emit_transition(
        self,
        event_type: str,
        previous: DecompositionSample,
        updated: DecompositionSample,
        *,
        actor: str,
        reason: str | None,
    ) -> None:
        payload = {
            "sample_id": updated.sample_id,
            "previous_state": previous.sample_state,
            "sample_state": updated.sample_state,
            "verify_kind": updated.verify_kind,
            "actor": actor,
        }
        if reason:
            payload["reason"] = reason
        self._emit(event_type, payload)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_stream is not None:
            self._event_stream.append(event_type, payload)

    def _require_sample(self, sample_id: str) -> DecompositionSample:
        sample = self._repository.get(sample_id)
        if sample is None:
            raise ValueError(f"decomposition sample not found: {sample_id}")
        return sample

    @staticmethod
    def _require_actor(actor: str, *, expected: str) -> None:
        normalized = str(actor).strip()
        if normalized != expected:
            raise InvalidSampleTransitionError(f"transition requires actor={expected}")

    @staticmethod
    def _require_reason(reason: str) -> str:
        normalized = str(reason).strip()
        if not normalized:
            raise ValueError("automatic sample transition requires reason")
        return normalized


class SampleRetriever:
    """摘要：仅从本地 verified 样本池检索并裁剪 few-shot 范例。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repository: SampleRepository,
        event_stream: EventStream | None = None,
        *,
        similarity_min: float = SAMPLE_SIMILARITY_MIN,
        similarity_reuse: float = SAMPLE_SIMILARITY_REUSE,
    ) -> None:
        """摘要：初始化样本检索器。"""
        self._conn = conn
        self._repository = repository
        self._event_stream = event_stream
        self._similarity_min = float(similarity_min)
        self._similarity_reuse = float(similarity_reuse)

    def retrieve(self, goal: str) -> list[SampleShot]:
        """摘要：检索最多两条异域范例，并在命中后更新审计与使用统计。"""
        normalized_goal = str(goal).strip()
        if not normalized_goal:
            return []
        candidates = [
            sample
            for sample in self._repository.list_samples(sample_state=SampleState.VERIFIED.value, limit=200)
            if sample.status == "active" and sample.verify_kind in {VerifyKind.USER.value, VerifyKind.AUTO.value}
        ]
        if not candidates:
            return []

        similarities = self._fused_similarities(normalized_goal, candidates)
        ranked: list[tuple[DecompositionSample, float, float]] = []
        now = time.time()
        for sample in candidates:
            similarity = similarities.get(sample.sample_id, 0.0)
            if similarity < self._similarity_min or similarity > self._similarity_reuse:
                continue
            quality = self._quality(sample, now=now)
            ranked.append((sample, similarity, similarity * quality))
        ranked.sort(key=lambda item: (item[2], item[1], item[0].updated_at), reverse=True)

        selected = self._select_diverse(ranked)
        shots: list[SampleShot] = []
        used_tokens = 0
        for sample, similarity, score in selected:
            shot = self._crop_sample(sample, similarity=similarity, score=score)
            if shot is None:
                continue
            if used_tokens + shot.token_count > SAMPLE_TOKEN_BUDGET:
                break
            shots.append(shot)
            used_tokens += shot.token_count

        goal_digest = hashlib.sha256(normalized_goal.encode("utf-8")).hexdigest()[:16]
        for shot in shots:
            self._repository.record_injection(
                shot.sample_id,
                hit_at=now,
                similarity=shot.similarity,
            )
            if self._event_stream is not None:
                self._event_stream.append(
                    "sample/injected",
                    {
                        "sample_id": shot.sample_id,
                        "goal_digest": goal_digest,
                        "sim_score": round(shot.similarity, 6),
                    },
                )
        return shots

    def _fused_similarities(
        self,
        goal: str,
        samples: list[DecompositionSample],
    ) -> dict[str, float]:
        """摘要：融合 BM25、确定性向量和词项重叠三路排名。"""
        sample_by_id = {sample.sample_id: sample for sample in samples}
        fts_values = self._fts_values(goal, set(sample_by_id))
        goal_tokens = set(tokenize_for_embedding(goal))
        goal_vector = embed_text(goal, dimensions=128)
        embedding_values: dict[str, float] = {}
        overlap_values: dict[str, float] = {}
        for sample in samples:
            sample_tokens = set(tokenize_for_embedding(sample.task_description))
            sample_vector = embed_text(sample.task_description, dimensions=128)
            embedding_values[sample.sample_id] = max(0.0, cosine_similarity(goal_vector, sample_vector))
            denominator = math.sqrt(len(goal_tokens) * len(sample_tokens))
            overlap_values[sample.sample_id] = (
                len(goal_tokens & sample_tokens) / denominator if denominator > 0 else 0.0
            )
        routes = (fts_values, embedding_values, overlap_values)
        fused = {sample_id: 0.0 for sample_id in sample_by_id}
        for values in routes:
            ranked_ids = [
                sample_id
                for sample_id, value in sorted(values.items(), key=lambda item: item[1], reverse=True)
                if value > 0.0
            ]
            for rank, sample_id in enumerate(ranked_ids, start=1):
                fused[sample_id] += values[sample_id] * (61.0 / (60.0 + rank)) / len(routes)
        return {sample_id: min(1.0, value) for sample_id, value in fused.items()}

    def _fts_values(self, goal: str, allowed_ids: set[str]) -> dict[str, float]:
        """摘要：执行带样本类型和 active 状态过滤的 BM25 检索。"""
        query = str(goal).strip().replace('"', " ")
        if not query or not allowed_ids:
            return {}
        try:
            rows = self._conn.execute(
                "SELECT m.id, bm25(memory_fts) AS score "
                "FROM memory_fts JOIN memory_chunks AS m ON m.id = memory_fts.rowid "
                "WHERE memory_fts MATCH ? AND m.memory_type = ? AND m.status = 'active' "
                "ORDER BY score LIMIT 200;",
                (f'"{query}"', SAMPLE_MEMORY_TYPE),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        values: dict[str, float] = {}
        for rank, row in enumerate(rows, start=1):
            sample_id = str(row["id"])
            if sample_id in allowed_ids:
                values[sample_id] = 61.0 / (60.0 + rank)
        return values

    @staticmethod
    def _quality(sample: DecompositionSample, *, now: float) -> float:
        """摘要：按成功率、新鲜度和验证来源计算可解释质量分。"""
        completed = max(0, int(sample.usage.get("plan_completed") or 0))
        failed = max(0, int(sample.usage.get("plan_failed") or 0))
        injected_count = max(0, int(sample.usage.get("injected_count") or 0))
        total = completed + failed
        success_rate = completed / total if injected_count >= 2 and total >= 2 else 0.5
        age_days = max(0.0, now - sample.updated_at) / 86400.0
        freshness = math.exp(-age_days / 90.0)
        verification = 1.0 if sample.verify_kind == VerifyKind.USER.value else 0.74
        return 0.5 * success_rate + 0.3 * freshness + 0.2 * verification

    @staticmethod
    def _select_diverse(
        ranked: list[tuple[DecompositionSample, float, float]],
    ) -> list[tuple[DecompositionSample, float, float]]:
        """摘要：选首条最高分样本，第二条必须来自不同工具签名。"""
        if not ranked:
            return []
        selected = [ranked[0]]
        first_signature = tuple(sorted(ranked[0][0].tool_refs))
        second = next(
            (item for item in ranked[1:] if tuple(sorted(item[0].tool_refs)) != first_signature),
            None,
        )
        if second is not None:
            selected.append(second)
        return selected[:SAMPLE_TOP_K]

    @classmethod
    def _crop_sample(
        cls,
        sample: DecompositionSample,
        *,
        similarity: float,
        score: float,
    ) -> SampleShot | None:
        """摘要：按字段长度和单样本 token 预算裁剪范例。"""
        description = cls._truncate(sample.task_description, 200)
        steps = cls._fit_steps(description, sample.steps, compact=False)
        if not steps:
            description = cls._truncate(sample.task_description, 60)
            steps = cls._fit_steps(description, sample.steps, compact=True)
        if not steps:
            return None
        token_count = cls._estimate_tokens(cls._render(description, steps))
        return SampleShot(
            sample_id=sample.sample_id,
            task_description=description,
            steps=tuple(steps),
            similarity=similarity,
            score=score,
            tool_refs=sample.tool_refs,
            token_count=token_count,
        )

    @classmethod
    def _fit_steps(
        cls,
        description: str,
        raw_steps: Iterable[Mapping[str, Any]],
        *,
        compact: bool,
    ) -> list[dict[str, str]]:
        """摘要：在单样本预算内尽可能保留完整步骤。"""
        limits = (60, 80, 60, 60) if compact else (80, 120, 80, 80)
        steps: list[dict[str, str]] = []
        for raw_step in raw_steps:
            cropped = {
                "title": cls._truncate(str(raw_step.get("title") or ""), limits[0]),
                "description": cls._truncate(str(raw_step.get("description") or ""), limits[1]),
                "verification": cls._truncate(str(raw_step.get("verification") or ""), limits[2]),
                "expected_output": cls._truncate(str(raw_step.get("expected_output") or ""), limits[3]),
            }
            if not cropped["title"]:
                continue
            tentative = (*steps, cropped)
            if cls._estimate_tokens(cls._render(description, tentative)) > SAMPLE_TOKEN_BUDGET_PER_ITEM:
                break
            steps.append(cropped)
        return steps

    @staticmethod
    def _render(task_description: str, steps: Iterable[Mapping[str, str]]) -> str:
        lines = [f"范例任务：{task_description}", "范例拆解："]
        for index, step in enumerate(steps, start=1):
            lines.extend(
                (
                    f"{index}. {step['title']} — {step['description']}",
                    f"   验证：{step['verification']}",
                    f"   产出：{step['expected_output']}",
                )
            )
        return "\n".join(lines)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        other_count = len(re.sub(r"[\u4e00-\u9fff\s]", "", text))
        return cjk_count + math.ceil(other_count / 4)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        normalized = str(value).strip()
        return normalized if len(normalized) <= limit else normalized[:limit]


class SampleMaintenance:
    """摘要：执行拆解样本容量淘汰与冷归档，不绕过用户主权状态机。"""

    def __init__(
        self,
        repository: SampleRepository,
        lifecycle: SampleLifecycleManager,
        *,
        plan_failed_provider: Callable[[str], bool] | None = None,
        verified_limit: int = 200,
    ) -> None:
        """摘要：初始化样本治理服务。

        参数：
            repository: 样本查询与统计仓储。
            lifecycle: 唯一状态迁移入口。
            plan_failed_provider: 判断关联计划是否已终态失败的本地回调。
            verified_limit: verified 池容量上限。
        """
        self._repository = repository
        self._lifecycle = lifecycle
        self._plan_failed_provider = plan_failed_provider or (lambda _plan_id: False)
        self._verified_limit = max(1, int(verified_limit))

    def run(self, now: float | None = None) -> list[str]:
        """摘要：执行一次幂等治理；任何迁移失败都会抛出以允许 IdleThink 重试。"""
        timestamp = float(time.time() if now is None else now)
        actions: list[str] = []
        errors: list[Exception] = []
        self._enforce_verified_limit(timestamp, actions, errors)
        self._archive_cold_and_abandoned(timestamp, actions, errors)
        if errors:
            raise RuntimeError(f"decomposition sample maintenance failed: {len(errors)} transition(s)")
        return actions

    def _enforce_verified_limit(
        self,
        now: float,
        actions: list[str],
        errors: list[Exception],
    ) -> None:
        verified = self._all_samples(sample_state=SampleState.VERIFIED.value)
        excess = max(0, len(verified) - self._verified_limit)
        if excess <= 0:
            return
        eligible = [
            sample
            for sample in verified
            if sample.verify_kind == VerifyKind.AUTO.value and sample.status == "active"
        ]
        eligible.sort(key=lambda sample: (self._eviction_score(sample, now=now), sample.updated_at))
        for sample in eligible[:excess]:
            self._archive(sample, reason="capacity", actions=actions, errors=errors)

    def _archive_cold_and_abandoned(
        self,
        now: float,
        actions: list[str],
        errors: list[Exception],
    ) -> None:
        cold_before = now - 90 * 86400.0
        abandoned_before = now - 30 * 86400.0
        for sample in self._all_samples():
            if sample.sample_state in {SampleState.REJECTED.value, SampleState.ARCHIVED.value}:
                continue
            if (
                sample.sample_state == SampleState.VERIFIED.value
                and sample.verify_kind == VerifyKind.USER.value
            ):
                continue
            last_injected_at = sample.usage.get("last_injected_at")
            if last_injected_at is not None:
                try:
                    if float(last_injected_at) < cold_before:
                        self._archive(sample, reason="cold", actions=actions, errors=errors)
                        continue
                except (TypeError, ValueError):
                    logger.warning("样本 %s 的 last_injected_at 非法，跳过冷归档", sample.sample_id)
            if (
                sample.sample_state == SampleState.CANDIDATE.value
                and sample.updated_at < abandoned_before
                and sample.plan_id
                and self._plan_failed_provider(sample.plan_id)
            ):
                self._archive(sample, reason="abandoned", actions=actions, errors=errors)

    def _archive(
        self,
        sample: DecompositionSample,
        *,
        reason: str,
        actions: list[str],
        errors: list[Exception],
    ) -> None:
        try:
            archived = self._lifecycle.archive(sample.sample_id, reason=reason, actor="system")
        except Exception as exc:  # noqa: BLE001
            logger.warning("样本 %s 治理迁移失败：%s", sample.sample_id, exc)
            errors.append(exc)
            return
        actions.append(f"{archived.sample_id}:{reason}")

    def _all_samples(self, *, sample_state: str | None = None) -> list[DecompositionSample]:
        samples: list[DecompositionSample] = []
        offset = 0
        while True:
            page = self._repository.list_samples(
                sample_state=sample_state,
                limit=500,
                offset=offset,
            )
            samples.extend(page)
            if len(page) < 500:
                return samples
            offset += len(page)

    @staticmethod
    def _eviction_score(sample: DecompositionSample, *, now: float) -> float:
        injected_count = max(0, int(sample.usage.get("injected_count") or 0))
        similarity_count = max(0, int(sample.usage.get("similarity_count") or 0))
        similarity_sum = max(0.0, float(sample.usage.get("similarity_sum") or 0.0))
        representative = similarity_sum / similarity_count if similarity_count > 0 else 0.0
        if injected_count == 0:
            representative = 0.0
        return representative * SampleRetriever._quality(sample, now=now)
