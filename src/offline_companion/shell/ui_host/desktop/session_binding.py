"""摘要：桌面会话人格快照、canonical 指针与原子切换服务。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from offline_companion.core.event_stream import EventStream, StreamManager
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.shared.types import OceanVector, Persona
from offline_companion.storage.persona_repo import active_persona, get_persona, init_personas

PERSONA_SNAPSHOT_SCHEMA = 1


class SessionBindingError(RuntimeError):
    """摘要：会话绑定失败，并携带稳定的 API 错误语义。"""

    def __init__(
        self,
        code: str,
        *,
        status: int = 409,
        state_unchanged: bool = True,
        canonical_session_id: str | None = None,
        revision: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.state_unchanged = state_unchanged
        self.canonical_session_id = canonical_session_id
        self.revision = revision


@dataclass(frozen=True)
class PersonaSnapshotProof:
    """摘要：可逐字节校验的会话人格快照。"""

    payload: dict[str, Any]
    canonical_json: str
    schema: int
    sha256: str
    source: str


@dataclass(frozen=True)
class DesktopSessionContext:
    """摘要：一次绑定后的不可变桌面会话上下文。"""

    session_id: str
    revision: int
    snapshot: PersonaSnapshotProof
    session_core: PersonaSessionCore
    event_stream: EventStream | None


class DesktopSessionContextProvider:
    """摘要：以单一原子引用发布当前桌面会话上下文。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._context: DesktopSessionContext | None = None
        self._recovery_required = False

    def capture(self) -> DesktopSessionContext:
        """摘要：捕获本轮操作必须持续使用的同一上下文。"""
        with self._lock:
            if self._recovery_required:
                raise SessionBindingError(
                    "session_recovery_required",
                    status=503,
                    state_unchanged=False,
                )
            if self._context is None:
                raise SessionBindingError(
                    "session_context_unavailable",
                    status=503,
                    state_unchanged=False,
                )
            return self._context

    def swap(self, context: DesktopSessionContext) -> None:
        """摘要：以一次指针替换发布已提交的会话上下文。"""
        with self._lock:
            self._context = context
            self._recovery_required = False

    def require_recovery(self) -> None:
        """摘要：提交后绑定失败时关闭消息通道，等待进程重启恢复。"""
        with self._lock:
            self._recovery_required = True


@dataclass(frozen=True)
class SessionSwitchResult:
    """摘要：人格切换 API 的稳定成功结果。"""

    context: DesktopSessionContext
    previous_session_id: str
    switch_request_id: str
    created_new_session: bool
    idempotent_replay: bool


@contextmanager
def immediate_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """摘要：在 autocommit 连接上提供唯一的显式立即事务边界。"""
    if conn.in_transaction:
        raise RuntimeError("nested_desktop_session_transaction")
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        try:
            conn.execute("COMMIT;")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK;")
            raise


def build_persona_snapshot(
    persona: Persona,
    *,
    source: str,
    effective_system_prompt: str | None = None,
    created_at: float | None = None,
) -> PersonaSnapshotProof:
    """摘要：从已解析人格构造 schema v1 canonical 快照与哈希。"""
    ocean = _normalized_ocean(persona.ocean)
    raw = persona.raw if isinstance(persona.raw, dict) else {}
    payload = {
        "companion_display_name": persona.companion_display_name,
        "constraint_manifest": {
            "sha256": raw.get("constraint_manifest_sha256"),
            "version": raw.get("constraint_manifest_version"),
        },
        "created_at": float(created_at if created_at is not None else time.time()),
        "default_companion_display_name": persona.default_companion_display_name,
        "effective_system_prompt": (
            persona.system_prompt if effective_system_prompt is None else str(effective_system_prompt)
        ),
        "memory_default_on": bool(persona.memory_default_on),
        "name": persona.name,
        "ocean": ocean,
        "ocean_levels": [_to_level(value) for value in ocean],
        "persona_id": persona.persona_id,
        "role_lock": bool(persona.role_lock),
        "source": str(source),
        "validated_anchor_id": raw.get("validated_anchor_id"),
        "validation_status": str(raw.get("validation_status") or "unvalidated"),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return PersonaSnapshotProof(
        payload=payload,
        canonical_json=canonical,
        schema=PERSONA_SNAPSHOT_SCHEMA,
        sha256=digest,
        source=str(source),
    )


def validate_persona_snapshot(row: sqlite3.Row) -> PersonaSnapshotProof:
    """摘要：校验 sessions 行内快照的 schema、canonical JSON 与 SHA-256。"""
    raw_json = row["persona_snapshot_json"]
    schema = row["persona_snapshot_schema"]
    digest = row["persona_snapshot_sha256"]
    source = row["persona_snapshot_source"]
    if raw_json is None or schema is None or digest is None or source is None:
        raise SessionBindingError("persona_snapshot_missing", status=409)
    if int(schema) != PERSONA_SNAPSHOT_SCHEMA:
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    try:
        payload = json.loads(str(raw_json))
    except (TypeError, json.JSONDecodeError) as exc:
        raise SessionBindingError("persona_snapshot_invalid", status=409) from exc
    if not isinstance(payload, dict):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    _validate_snapshot_payload(payload, row)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    calculated = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if canonical != str(raw_json) or calculated != str(digest):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    if str(payload.get("source") or "") != str(source):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    return PersonaSnapshotProof(
        payload=payload,
        canonical_json=canonical,
        schema=int(schema),
        sha256=calculated,
        source=str(source),
    )


class DesktopSessionBindingService:
    """摘要：恢复、创建并原子切换 canonical 桌面会话。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        context_provider: DesktopSessionContextProvider,
        event_stream_manager: StreamManager | None,
        semantic_embed_func: Callable[[str], list[float]] | None,
        on_bind: Callable[[DesktopSessionContext], None] | None = None,
        after_commit_hook: Callable[[DesktopSessionContext], None] | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._conn = conn
        self._context_provider = context_provider
        self._event_stream_manager = event_stream_manager
        self._semantic_embed_func = semantic_embed_func
        self._on_bind = on_bind
        self._after_commit_hook = after_commit_hook
        self._fault_injector = fault_injector
        self._switch_lock = threading.Lock()

    def set_on_bind(self, callback: Callable[[DesktopSessionContext], None]) -> None:
        """摘要：注册提交后运行时投影重绑定回调。"""
        self._on_bind = callback

    def restore_or_create(
        self,
        *,
        preferred_session_id: str,
        startup_persona: Persona,
        title: str,
    ) -> DesktopSessionContext:
        """摘要：从 SQLite canonical 恢复，缺失时创建首个可恢复会话。"""
        init_personas(self._conn)
        self._backfill_legacy_sessions(startup_persona=startup_persona)
        state = self._state_row()
        if state is not None:
            context = self._context_for_session(str(state["active_session_id"]), int(state["revision"]))
            self._publish(context)
            return context

        row = self._session_row(preferred_session_id)
        if row is not None:
            try:
                proof = validate_persona_snapshot(row)
            except SessionBindingError:
                proof = None
            if proof is not None:
                session_id = preferred_session_id
            else:
                session_id = self._latest_recoverable_session_id()
        else:
            session_id = self._latest_recoverable_session_id()

        if session_id is None:
            default_persona = active_persona(self._conn) or startup_persona
            proof = build_persona_snapshot(default_persona, source="bootstrap")
            session_id = preferred_session_id if row is None and preferred_session_id else uuid.uuid4().hex
            with immediate_transaction(self._conn):
                self._insert_session(
                    session_id=session_id,
                    persona_id=default_persona.persona_id,
                    title=title,
                    proof=proof,
                    switch_request_id=None,
                )
                self._insert_initial_state(session_id)
        else:
            with immediate_transaction(self._conn):
                self._insert_initial_state(session_id)

        context = self._context_for_session(session_id, 1)
        self._publish(context)
        return context

    def current(self) -> DesktopSessionContext:
        """摘要：读取并校验 SQLite canonical 会话。"""
        state = self._state_row()
        if state is None:
            raise SessionBindingError("canonical_session_missing", status=503, state_unchanged=False)
        return self._context_for_session(str(state["active_session_id"]), int(state["revision"]))

    def switch_persona(
        self,
        target_persona_id: str,
        *,
        switch_request_id: str,
        expected_revision: int,
        title: str | None = None,
    ) -> SessionSwitchResult:
        """摘要：以单飞、幂等和显式事务切换到新人格会话。"""
        if not self._switch_lock.acquire(blocking=False):
            state = self._state_row()
            raise self._conflict("switch_in_progress", state)
        try:
            return self._switch_locked(
                target_persona_id,
                switch_request_id=switch_request_id,
                expected_revision=expected_revision,
                title=title,
            )
        finally:
            self._switch_lock.release()

    def _switch_locked(
        self,
        target_persona_id: str,
        *,
        switch_request_id: str,
        expected_revision: int,
        title: str | None,
    ) -> SessionSwitchResult:
        request_id = str(switch_request_id).strip()
        if not request_id:
            state = self._state_row()
            raise self._conflict("switch_request_id_required", state, status=400)
        state = self._state_row()
        if state is None:
            raise SessionBindingError("canonical_session_missing", status=503, state_unchanged=False)
        replay = self._idempotent_replay(request_id, target_persona_id, state)
        if replay is not None:
            return replay
        if int(expected_revision) != int(state["revision"]):
            raise self._conflict("revision_conflict", state)
        persona = get_persona(self._conn, target_persona_id)
        if persona is None:
            raise self._conflict("persona_not_found", state, status=404)

        try:
            proof = build_persona_snapshot(persona, source="persona_switch")
            self._inject_fault("snapshot")
            new_session_id = uuid.uuid4().hex
            previous_session_id = str(state["active_session_id"])
            next_revision = int(state["revision"]) + 1
            prepared = self._build_context(new_session_id, next_revision, proof)
        except Exception as exc:
            raise self._conflict("switch_failed", state) from exc
        try:
            with immediate_transaction(self._conn):
                locked_state = self._state_row()
                if locked_state is None or int(locked_state["revision"]) != int(expected_revision):
                    raise self._conflict("revision_conflict", locked_state or state)
                duplicate = self._conn.execute(
                    "SELECT persona_id FROM sessions WHERE switch_request_id = ?;",
                    (request_id,),
                ).fetchone()
                if duplicate is not None:
                    raise self._conflict("switch_request_conflict", locked_state)
                self._insert_session(
                    session_id=new_session_id,
                    persona_id=persona.persona_id,
                    title=title or f"{persona.name} 会话",
                    proof=proof,
                    switch_request_id=request_id,
                )
                self._inject_fault("session")
                now = time.time()
                self._conn.execute("UPDATE personas SET active = 0, updated_at = ? WHERE active = 1;", (now,))
                self._conn.execute(
                    "UPDATE personas SET active = 1, updated_at = ? WHERE id = ?;",
                    (now, persona.persona_id),
                )
                self._inject_fault("default")
                self._conn.execute(
                    """
                    UPDATE desktop_session_state
                    SET active_session_id = ?, revision = ?, updated_at = ?
                    WHERE id = 1;
                    """,
                    (new_session_id, next_revision, now),
                )
                self._inject_fault("canonical")
        except SessionBindingError:
            raise
        except Exception as exc:
            raise self._conflict("switch_failed", state) from exc

        self._publish_committed(prepared)
        return SessionSwitchResult(
            context=prepared,
            previous_session_id=previous_session_id,
            switch_request_id=request_id,
            created_new_session=True,
            idempotent_replay=False,
        )

    def _idempotent_replay(
        self,
        request_id: str,
        target_persona_id: str,
        state: sqlite3.Row,
    ) -> SessionSwitchResult | None:
        row = self._conn.execute(
            "SELECT id, persona_id FROM sessions WHERE switch_request_id = ?;",
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["persona_id"]) != target_persona_id or str(row["id"]) != str(state["active_session_id"]):
            raise self._conflict("switch_request_conflict", state)
        context = self._context_for_session(str(row["id"]), int(state["revision"]))
        self._publish_committed(context, run_after_commit_hook=False)
        return SessionSwitchResult(
            context=context,
            previous_session_id=str(row["id"]),
            switch_request_id=request_id,
            created_new_session=False,
            idempotent_replay=True,
        )

    def _backfill_legacy_sessions(self, *, startup_persona: Persona) -> None:
        rows = self._conn.execute(
            "SELECT id, persona_id FROM sessions WHERE persona_snapshot_json IS NULL;"
        ).fetchall()
        if not rows:
            return
        proofs: list[tuple[PersonaSnapshotProof, str]] = []
        for row in rows:
            persona = get_persona(self._conn, str(row["persona_id"]))
            if persona is None and str(row["persona_id"]) == startup_persona.persona_id:
                persona = startup_persona
            if persona is not None:
                proofs.append((build_persona_snapshot(persona, source="legacy_backfill"), str(row["id"])))
        if not proofs:
            return
        with immediate_transaction(self._conn):
            for proof, session_id in proofs:
                self._conn.execute(
                    """
                    UPDATE sessions
                    SET persona_snapshot_json = ?, persona_snapshot_schema = ?,
                        persona_snapshot_sha256 = ?, persona_snapshot_source = ?
                    WHERE id = ? AND persona_snapshot_json IS NULL;
                    """,
                    (proof.canonical_json, proof.schema, proof.sha256, proof.source, session_id),
                )

    def _context_for_session(self, session_id: str, revision: int) -> DesktopSessionContext:
        row = self._session_row(session_id)
        if row is None:
            raise SessionBindingError("canonical_session_missing", status=503, state_unchanged=False)
        proof = validate_persona_snapshot(row)
        return self._build_context(session_id, revision, proof)

    def _build_context(
        self,
        session_id: str,
        revision: int,
        proof: PersonaSnapshotProof,
    ) -> DesktopSessionContext:
        persona = _persona_from_snapshot(proof.payload)
        stream = None
        if self._event_stream_manager is not None:
            get_or_create = getattr(self._event_stream_manager, "get_or_create", None)
            if callable(get_or_create):
                stream = get_or_create(session_id)
            else:
                get_stream = getattr(self._event_stream_manager, "get", None)
                stream = get_stream(session_id) if callable(get_stream) else None
        return DesktopSessionContext(
            session_id=session_id,
            revision=revision,
            snapshot=proof,
            session_core=PersonaSessionCore(persona, semantic_embed_func=self._semantic_embed_func),
            event_stream=stream,
        )

    def _publish(self, context: DesktopSessionContext) -> None:
        self._context_provider.swap(context)
        if self._on_bind is not None:
            self._on_bind(context)

    def _publish_committed(
        self,
        context: DesktopSessionContext,
        *,
        run_after_commit_hook: bool = True,
    ) -> None:
        try:
            if run_after_commit_hook and self._after_commit_hook is not None:
                self._after_commit_hook(context)
            self._publish(context)
        except Exception as exc:
            self._context_provider.require_recovery()
            raise SessionBindingError(
                "session_recovery_required",
                status=503,
                state_unchanged=False,
                canonical_session_id=context.session_id,
                revision=context.revision,
            ) from exc

    def _session_row(self, session_id: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,)).fetchone()

    def _state_row(self) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM desktop_session_state WHERE id = 1;").fetchone()

    def _latest_recoverable_session_id(self) -> str | None:
        rows = self._conn.execute(
            """
            SELECT * FROM sessions
            WHERE persona_snapshot_json IS NOT NULL
            ORDER BY updated_at DESC, created_at DESC, id DESC;
            """
        ).fetchall()
        for row in rows:
            try:
                validate_persona_snapshot(row)
            except SessionBindingError:
                continue
            return str(row["id"])
        return None

    def _insert_initial_state(self, session_id: str) -> None:
        self._conn.execute(
            """
            INSERT INTO desktop_session_state(id, active_session_id, revision, updated_at)
            VALUES(1, ?, 1, ?);
            """,
            (session_id, time.time()),
        )

    def _insert_session(
        self,
        *,
        session_id: str,
        persona_id: str,
        title: str | None,
        proof: PersonaSnapshotProof,
        switch_request_id: str | None,
    ) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO sessions(
                id, title, persona_id, created_at, updated_at,
                persona_snapshot_json, persona_snapshot_schema, persona_snapshot_sha256,
                persona_snapshot_source, switch_request_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?);
            """,
            (
                session_id,
                title,
                persona_id,
                now,
                now,
                proof.canonical_json,
                proof.schema,
                proof.sha256,
                proof.source,
                switch_request_id,
            ),
        )

    def _inject_fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)

    @staticmethod
    def _conflict(
        code: str,
        state: sqlite3.Row,
        *,
        status: int = 409,
    ) -> SessionBindingError:
        return SessionBindingError(
            code,
            status=status,
            state_unchanged=True,
            canonical_session_id=str(state["active_session_id"]),
            revision=int(state["revision"]),
        )


def _normalized_ocean(ocean: OceanVector | None) -> list[int]:
    if ocean is None:
        return [50, 50, 50, 50, 50]
    return [
        round(ocean.openness * 100),
        round(ocean.conscientiousness * 100),
        round(ocean.extraversion * 100),
        round(ocean.agreeableness * 100),
        round(ocean.neuroticism * 100),
    ]


def _to_level(value: int) -> str:
    if value <= 33:
        return "low"
    if value <= 66:
        return "mid"
    return "high"


def _persona_from_snapshot(payload: dict[str, Any]) -> Persona:
    ocean_values = payload.get("ocean")
    if not isinstance(ocean_values, list) or len(ocean_values) != 5:
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    try:
        normalized = [max(0, min(100, int(value))) for value in ocean_values]
    except (TypeError, ValueError) as exc:
        raise SessionBindingError("persona_snapshot_invalid", status=409) from exc
    prompt = payload.get("effective_system_prompt")
    if not isinstance(prompt, str) or not prompt:
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    persona_id = str(payload.get("persona_id") or "")
    name = str(payload.get("name") or "")
    if not persona_id or not name:
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    ocean = OceanVector(
        openness=normalized[0] / 100,
        conscientiousness=normalized[1] / 100,
        extraversion=normalized[2] / 100,
        agreeableness=normalized[3] / 100,
        neuroticism=normalized[4] / 100,
    )
    return Persona(
        persona_id=persona_id,
        name=name,
        system_prompt=prompt,
        role_lock=bool(payload.get("role_lock", True)),
        memory_default_on=bool(payload.get("memory_default_on", True)),
        default_companion_display_name=str(payload.get("default_companion_display_name") or name),
        companion_display_name=(
            str(payload["companion_display_name"])
            if payload.get("companion_display_name") is not None
            else None
        ),
        raw={
            "validation_status": payload.get("validation_status"),
            "validated_anchor_id": payload.get("validated_anchor_id"),
            "constraint_manifest": payload.get("constraint_manifest"),
            "snapshot_source": payload.get("source"),
        },
        ocean=ocean,
    )


def _validate_snapshot_payload(payload: dict[str, Any], row: sqlite3.Row) -> None:
    required_text = (
        "persona_id",
        "name",
        "default_companion_display_name",
        "effective_system_prompt",
        "source",
        "validation_status",
    )
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required_text):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    if str(payload["persona_id"]) != str(row["persona_id"]):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    if not isinstance(payload.get("role_lock"), bool) or not isinstance(
        payload.get("memory_default_on"), bool
    ):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    if not isinstance(payload.get("created_at"), (int, float)):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    ocean = payload.get("ocean")
    levels = payload.get("ocean_levels")
    if not isinstance(ocean, list) or len(ocean) != 5:
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100 for value in ocean):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    if levels != [_to_level(value) for value in ocean]:
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    manifest = payload.get("constraint_manifest")
    if not isinstance(manifest, dict) or set(manifest) != {"version", "sha256"}:
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    if any(value is not None and not isinstance(value, str) for value in manifest.values()):
        raise SessionBindingError("persona_snapshot_invalid", status=409)
    for optional_text in ("companion_display_name", "validated_anchor_id"):
        value = payload.get(optional_text)
        if value is not None and not isinstance(value, str):
            raise SessionBindingError("persona_snapshot_invalid", status=409)


def rebind_runtime_session(runtime: Any, context: DesktopSessionContext) -> None:
    """摘要：把兼容字段与长生命周期组件统一投影到同一 context。"""
    stream = context.event_stream
    runtime.session_id = context.session_id
    runtime.persona_name = (
        context.session_core.persona.companion_display_name
        or context.session_core.persona.default_companion_display_name
    )
    runtime.orchestrator.session_id = context.session_id
    runtime.orchestrator.session_core = context.session_core
    runtime.orchestrator.event_stream = stream
    consent_gateway = runtime.orchestrator.consent_gateway
    if consent_gateway is not None:
        consent_gateway.event_stream = stream
    tool_invoker = runtime.orchestrator.tool_invoker
    if tool_invoker is not None:
        tool_invoker.event_stream = stream
    if runtime.sample_lifecycle is not None:
        runtime.sample_lifecycle._event_stream = stream
    if runtime.sample_retriever is not None:
        runtime.sample_retriever._event_stream = stream
    if runtime.auto_turn_orchestrator is not None:
        runtime.auto_turn_orchestrator.event_stream = stream
    plan_orchestrator = runtime.plan_orchestrator
    publisher = getattr(plan_orchestrator, "_event_publisher", None)
    if publisher is not None and hasattr(publisher, "_stream"):
        publisher._stream = stream
    downloader = runtime.model_downloader
    if downloader is not None and hasattr(downloader, "_event_stream"):
        downloader._event_stream = stream
