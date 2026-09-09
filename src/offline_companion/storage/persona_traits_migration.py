"""摘要：保全旧人格手写 traits 并管理可恢复的 v15 迁移状态。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from offline_companion.core.persona_constraint.levels import (
    CUTPOINT_VERSION,
    PersonaLevelDerivationError,
    derive_levels,
    serialize_levels,
)

PERSONA_TRAITS_MIGRATION_ID = "persona_traits_to_ocean_v1"
PERSONA_TRAITS_EXPORT_FILENAME = "persona_traits_migration_v1.json"
PERSONA_TRAITS_EXPORT_SCHEMA_VERSION = 1

_LOGGER = logging.getLogger(__name__)


class PersonaTraitsMigrationError(RuntimeError):
    """摘要：人格 traits 保全导出或迁移状态不满足契约。"""


@dataclass(frozen=True)
class PersonaTraitsMigrationState:
    """摘要：人格 traits 迁移的持久化状态投影。"""

    status: str
    export_path: Path
    record_count: int
    export_sha256: str


def prepare_persona_traits_migration(
    conn: Any,
    *,
    exports_dir: Path,
) -> PersonaTraitsMigrationState:
    """摘要：校验或创建旧 traits 导出，并将迁移状态推进到 exported。

    参数：
        conn: 已完成 v15 schema 迁移的 SQLite 连接。
        exports_dir: 当前 runtime 注入的导出目录。

    返回值：
        已持久化且校验通过的迁移状态。

    Raises:
        PersonaTraitsMigrationError: 导出、完整性或恢复状态不满足契约。
    """
    export_path = exports_dir / PERSONA_TRAITS_EXPORT_FILENAME
    persisted = _load_state(conn)
    if persisted is not None:
        _validate_state_path(persisted, export_path)
        payload = _read_and_validate_export(export_path)
        _validate_state_payload(persisted, payload)
        if persisted.status == "exported":
            _validate_exported_records_unchanged(conn, payload)
        return persisted

    records = _read_legacy_records(conn)
    expected_payload = _build_export_payload(records)
    if export_path.exists():
        payload = _read_and_validate_export(export_path)
        if payload != expected_payload:
            raise PersonaTraitsMigrationError("persona_traits_export_existing_mismatch")
    else:
        _write_export_atomic(export_path, expected_payload)
        payload = _read_and_validate_export(export_path)
        if payload != expected_payload:
            raise PersonaTraitsMigrationError("persona_traits_export_verification_mismatch")

    state = PersonaTraitsMigrationState(
        status="exported",
        export_path=export_path.resolve(),
        record_count=int(payload["record_count"]),
        export_sha256=str(payload["sha256"]),
    )
    _store_exported_state(conn, state)
    return state


def complete_persona_level_migration(conn: Any) -> int:
    """摘要：原子刷新全部人格档位缓存并将迁移状态推进到 completed。

    参数：
        conn: 已完成 v15 schema 迁移且已生成保全导出的 SQLite 连接。

    返回值：
        完成一致性校验或刷新的 persona 行数。

    Raises:
        PersonaTraitsMigrationError: 保全导出未完成或任一 OCEAN 向量非法。
    """
    state = _load_state(conn)
    if state is None:
        raise PersonaTraitsMigrationError("persona_traits_export_required")
    rows = conn.execute(
        """
        SELECT id, ocean_json, derived_levels_json, derived_cutpoint_version
        FROM personas
        ORDER BY id;
        """
    ).fetchall()
    expected: list[tuple[str, str]] = []
    for row in rows:
        try:
            ocean = json.loads(str(row["ocean_json"]))
            levels_json = serialize_levels(derive_levels(ocean))
        except (json.JSONDecodeError, TypeError, PersonaLevelDerivationError) as exc:
            raise PersonaTraitsMigrationError(f"persona_ocean_invalid:{row['id']}") from exc
        expected.append((str(row["id"]), levels_json))

    if state.status == "completed":
        for row, (_, levels_json) in zip(rows, expected, strict=True):
            if (
                str(row["derived_levels_json"]) != levels_json
                or str(row["derived_cutpoint_version"]) != CUTPOINT_VERSION
            ):
                raise PersonaTraitsMigrationError(
                    f"persona_level_cache_inconsistent:{row['id']}"
                )
        return len(expected)

    conn.execute("BEGIN IMMEDIATE;")
    try:
        for persona_id, levels_json in expected:
            conn.execute(
                """
                UPDATE personas
                SET derived_levels_json = ?, derived_cutpoint_version = ?
                WHERE id = ?;
                """,
                (levels_json, CUTPOINT_VERSION, persona_id),
            )
        conn.execute(
            """
            UPDATE persona_migration_state
            SET status = 'completed', updated_at = ?
            WHERE migration_id = ? AND status = 'exported';
            """,
            (time.time(), PERSONA_TRAITS_MIGRATION_ID),
        )
        if conn.execute("SELECT changes();").fetchone()[0] != 1:
            raise PersonaTraitsMigrationError("persona_traits_migration_state_conflict")
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")
    return len(expected)


def _read_legacy_records(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, name, traits_json, raw_json, ocean_json, updated_at
        FROM personas
        ORDER BY id ASC;
        """
    ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        traits_json = str(row["traits_json"])
        raw_json = str(row["raw_json"])
        raw_traits, resolution = _resolve_raw_traits(raw_json, traits_json, persona_id=str(row["id"]))
        records.append(
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "traits_json": traits_json,
                "raw_json": raw_json,
                "raw_json_traits": raw_traits,
                "traits_resolution": resolution,
                "ocean_json": str(row["ocean_json"]),
                "updated_at": row["updated_at"],
            }
        )
    return records


def _resolve_raw_traits(raw_json: str, traits_json: str, *, persona_id: str) -> tuple[list[Any], str]:
    raw_value: Any = None
    try:
        parsed_raw = json.loads(raw_json)
    except json.JSONDecodeError:
        parsed_raw = None
    if isinstance(parsed_raw, dict):
        raw_value = parsed_raw.get("traits")

    try:
        parsed_traits = json.loads(traits_json)
    except json.JSONDecodeError:
        parsed_traits = None

    if _is_valid_traits(raw_value):
        if _is_valid_traits(parsed_traits) and raw_value != parsed_traits:
            _LOGGER.warning(
                "persona/traits_source_conflict persona_id=%s source=raw_json.traits",
                persona_id,
            )
            return raw_value, "raw_json_traits_conflict"
        return raw_value, "raw_json_traits"
    if _is_valid_traits(parsed_traits):
        _LOGGER.warning(
            "persona/traits_source_fallback persona_id=%s reason=raw_json_traits_invalid",
            persona_id,
        )
        return parsed_traits, "traits_json_fallback"
    _LOGGER.warning(
        "persona/traits_source_fallback persona_id=%s reason=both_invalid",
        persona_id,
    )
    return [], "empty_fallback"


def _is_valid_traits(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _build_export_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schema_version": PERSONA_TRAITS_EXPORT_SCHEMA_VERSION,
        "migration_id": PERSONA_TRAITS_MIGRATION_ID,
        "record_count": len(records),
        "records": records,
    }
    digest = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    return {**body, "sha256": digest}


def _read_and_validate_export(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersonaTraitsMigrationError("persona_traits_export_unreadable") from exc
    if not isinstance(payload, dict):
        raise PersonaTraitsMigrationError("persona_traits_export_invalid")
    if payload.get("schema_version") != PERSONA_TRAITS_EXPORT_SCHEMA_VERSION:
        raise PersonaTraitsMigrationError("persona_traits_export_schema_mismatch")
    if payload.get("migration_id") != PERSONA_TRAITS_MIGRATION_ID:
        raise PersonaTraitsMigrationError("persona_traits_export_migration_mismatch")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("record_count") != len(records):
        raise PersonaTraitsMigrationError("persona_traits_export_count_mismatch")
    body = {key: value for key, value in payload.items() if key != "sha256"}
    digest = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    if payload.get("sha256") != digest:
        raise PersonaTraitsMigrationError("persona_traits_export_hash_mismatch")
    return payload


def _validate_exported_records_unchanged(conn: Any, payload: dict[str, Any]) -> None:
    current_by_id = {record["id"]: record for record in _read_legacy_records(conn)}
    for exported in payload["records"]:
        current = current_by_id.get(exported.get("id"))
        if current != exported:
            raise PersonaTraitsMigrationError("persona_traits_export_database_mismatch")


def _write_export_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise PersonaTraitsMigrationError("persona_traits_export_already_exists")
        os.replace(temp_path, path)
    except OSError as exc:
        raise PersonaTraitsMigrationError("persona_traits_export_write_failed") from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _load_state(conn: Any) -> PersonaTraitsMigrationState | None:
    row = conn.execute(
        """
        SELECT status, export_path, record_count, export_sha256
        FROM persona_migration_state
        WHERE migration_id = ?;
        """,
        (PERSONA_TRAITS_MIGRATION_ID,),
    ).fetchone()
    if row is None:
        return None
    return PersonaTraitsMigrationState(
        status=str(row["status"]),
        export_path=Path(str(row["export_path"])),
        record_count=int(row["record_count"]),
        export_sha256=str(row["export_sha256"]),
    )


def _store_exported_state(conn: Any, state: PersonaTraitsMigrationState) -> None:
    conn.execute("BEGIN IMMEDIATE;")
    try:
        conn.execute(
            """
            INSERT INTO persona_migration_state(
                migration_id, status, export_path, record_count, export_sha256, updated_at
            ) VALUES(?,?,?,?,?,?);
            """,
            (
                PERSONA_TRAITS_MIGRATION_ID,
                state.status,
                str(state.export_path),
                state.record_count,
                state.export_sha256,
                time.time(),
            ),
        )
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


def _validate_state_path(state: PersonaTraitsMigrationState, expected_path: Path) -> None:
    if state.status not in {"exported", "completed"}:
        raise PersonaTraitsMigrationError("persona_traits_migration_status_invalid")
    if state.export_path.resolve() != expected_path.resolve():
        raise PersonaTraitsMigrationError("persona_traits_export_path_mismatch")


def _validate_state_payload(state: PersonaTraitsMigrationState, payload: dict[str, Any]) -> None:
    if state.record_count != payload["record_count"]:
        raise PersonaTraitsMigrationError("persona_traits_migration_count_mismatch")
    if state.export_sha256 != payload["sha256"]:
        raise PersonaTraitsMigrationError("persona_traits_migration_hash_mismatch")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
