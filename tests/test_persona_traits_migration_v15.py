"""摘要：P3-A2 v15 手写 traits 保全迁移测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from offline_companion.runtime.storage_index.engine import SCHEMA_VERSION, connect
from offline_companion.storage import persona_traits_migration as migration_module
from offline_companion.storage.persona_repo import init_personas
from offline_companion.storage.persona_traits_migration import (
    PERSONA_TRAITS_EXPORT_FILENAME,
    PERSONA_TRAITS_MIGRATION_ID,
    PersonaTraitsMigrationError,
    prepare_persona_traits_migration,
)


def _canonical(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _persona_rows(conn) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, name, traits_json, raw_json, ocean_json, updated_at,
                   derived_traits_json, derived_levels_json
            FROM personas
            ORDER BY id;
            """
        ).fetchall()
    ]


def test_v15_schema_adds_isolated_derived_columns_and_state_table(tmp_path: Path) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        version = int(conn.execute("SELECT value FROM meta WHERE key = 'schema_version';").fetchone()[0])
        columns = {row[1] for row in conn.execute("PRAGMA table_info(personas);").fetchall()}
        state_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'persona_migration_state';"
        ).fetchone()[0]

        assert version == SCHEMA_VERSION == 15
        assert {
            "derived_traits_json",
            "derived_levels_json",
            "derived_cutpoint_version",
        } <= columns
        assert "'exported', 'completed'" in state_sql
    finally:
        conn.close()


def test_export_preserves_dual_traits_verbatim_and_uses_raw_on_conflict(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        init_personas(conn)
        conn.execute(
            """
            UPDATE personas
            SET traits_json = ?, raw_json = ?
            WHERE id = 'xiao_nuo';
            """,
            (
                '[" traits-column ", "保留顺序"]',
                '{"traits":[" raw-first ","保留顺序"],"legacy_extra":{"keep":true}}',
            ),
        )
        before = _persona_rows(conn)

        state = prepare_persona_traits_migration(conn, exports_dir=tmp_path / "chosen-exports")

        after = _persona_rows(conn)
        payload = json.loads(state.export_path.read_text(encoding="utf-8"))
        body = {key: value for key, value in payload.items() if key != "sha256"}
        target = next(record for record in payload["records"] if record["id"] == "xiao_nuo")
        assert after == before
        assert state.status == "exported"
        assert state.export_path == (tmp_path / "chosen-exports" / PERSONA_TRAITS_EXPORT_FILENAME).resolve()
        assert payload["record_count"] == len(before)
        assert payload["sha256"] == hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        assert target["traits_json"] == '[" traits-column ", "保留顺序"]'
        assert target["raw_json"] == '{"traits":[" raw-first ","保留顺序"],"legacy_extra":{"keep":true}}'
        assert target["raw_json_traits"] == [" raw-first ", "保留顺序"]
        assert target["traits_resolution"] == "raw_json_traits_conflict"
        assert target["ocean_json"] == next(row["ocean_json"] for row in before if row["id"] == "xiao_nuo")
        assert "persona/traits_source_conflict" in caplog.text
    finally:
        conn.close()


def test_export_is_self_contained_for_future_traits_restore(tmp_path: Path) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        init_personas(conn)
        original = _persona_rows(conn)

        state = prepare_persona_traits_migration(conn, exports_dir=tmp_path / "exports")
        records = json.loads(state.export_path.read_text(encoding="utf-8"))["records"]

        restored = {
            record["id"]: {
                "name": record["name"],
                "traits_json": record["traits_json"],
                "raw_json": record["raw_json"],
                "ocean_json": record["ocean_json"],
                "updated_at": record["updated_at"],
            }
            for record in records
        }
        expected = {
            str(row["id"]): {
                "name": row["name"],
                "traits_json": row["traits_json"],
                "raw_json": row["raw_json"],
                "ocean_json": row["ocean_json"],
                "updated_at": row["updated_at"],
            }
            for row in original
        }
        assert restored == expected
    finally:
        conn.close()


def test_existing_valid_export_is_reused_without_overwrite(tmp_path: Path) -> None:
    db_path = tmp_path / "companion.db"
    exports_dir = tmp_path / "exports"
    conn = connect(db_path)
    init_personas(conn)
    first = prepare_persona_traits_migration(conn, exports_dir=exports_dir)
    original_bytes = first.export_path.read_bytes()
    original_mtime = first.export_path.stat().st_mtime_ns
    conn.execute(
        "DELETE FROM persona_migration_state WHERE migration_id = ?;",
        (PERSONA_TRAITS_MIGRATION_ID,),
    )
    conn.close()

    reopened = connect(db_path)
    try:
        second = prepare_persona_traits_migration(reopened, exports_dir=exports_dir)
        assert second == first
        assert second.export_path.read_bytes() == original_bytes
        assert second.export_path.stat().st_mtime_ns == original_mtime
    finally:
        reopened.close()


def test_invalid_raw_traits_falls_back_without_normalizing_legacy_text(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        init_personas(conn)
        conn.execute(
            """
            UPDATE personas
            SET traits_json = ?, raw_json = ?
            WHERE id = 'a_ce';
            """,
            ('[" traits fallback ", "原序"]', '{"traits":[1,"非法混合"],"keep":"yes"}'),
        )
        before = _persona_rows(conn)

        state = prepare_persona_traits_migration(conn, exports_dir=tmp_path / "exports")
        payload = json.loads(state.export_path.read_text(encoding="utf-8"))
        target = next(record for record in payload["records"] if record["id"] == "a_ce")

        assert _persona_rows(conn) == before
        assert target["raw_json"] == '{"traits":[1,"非法混合"],"keep":"yes"}'
        assert target["traits_json"] == '[" traits fallback ", "原序"]'
        assert target["raw_json_traits"] == [" traits fallback ", "原序"]
        assert target["traits_resolution"] == "traits_json_fallback"
        assert "persona/traits_source_fallback" in caplog.text
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda payload: payload.update(record_count=payload["record_count"] + 1), "count_mismatch"),
        (lambda payload: payload.update(sha256="0" * 64), "hash_mismatch"),
    ],
)
def test_invalid_existing_export_causes_zero_database_change(
    tmp_path: Path,
    mutator,
    error: str,
) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        init_personas(conn)
        before = _persona_rows(conn)
        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()
        export_path = exports_dir / PERSONA_TRAITS_EXPORT_FILENAME
        payload = {
            "schema_version": 1,
            "migration_id": PERSONA_TRAITS_MIGRATION_ID,
            "record_count": 0,
            "records": [],
            "sha256": "unused",
        }
        mutator(payload)
        export_path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(PersonaTraitsMigrationError, match=error):
            prepare_persona_traits_migration(conn, exports_dir=exports_dir)

        assert _persona_rows(conn) == before
        assert conn.execute("SELECT COUNT(*) FROM persona_migration_state;").fetchone()[0] == 0
    finally:
        conn.close()


def test_export_write_failure_causes_zero_database_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        init_personas(conn)
        before = _persona_rows(conn)

        def fail_write(path: Path, payload: dict[str, object]) -> None:
            del path, payload
            raise PersonaTraitsMigrationError("injected_export_failure")

        monkeypatch.setattr(migration_module, "_write_export_atomic", fail_write)
        with pytest.raises(PersonaTraitsMigrationError, match="injected_export_failure"):
            prepare_persona_traits_migration(conn, exports_dir=tmp_path / "exports")

        assert _persona_rows(conn) == before
        assert conn.execute("SELECT COUNT(*) FROM persona_migration_state;").fetchone()[0] == 0
    finally:
        conn.close()


def test_exported_and_completed_states_resume_with_consistency_check(tmp_path: Path) -> None:
    db_path = tmp_path / "companion.db"
    exports_dir = tmp_path / "exports"
    conn = connect(db_path)
    init_personas(conn)
    exported = prepare_persona_traits_migration(conn, exports_dir=exports_dir)
    conn.close()

    reopened = connect(db_path)
    resumed = prepare_persona_traits_migration(reopened, exports_dir=exports_dir)
    assert resumed.status == "exported"
    reopened.execute(
        "UPDATE persona_migration_state SET status = 'completed' WHERE migration_id = ?;",
        (PERSONA_TRAITS_MIGRATION_ID,),
    )
    reopened.close()

    completed_conn = connect(db_path)
    try:
        completed = prepare_persona_traits_migration(completed_conn, exports_dir=exports_dir)
        assert completed.status == "completed"
        assert completed.export_sha256 == exported.export_sha256
    finally:
        completed_conn.close()


def test_tone_keywords_stays_local_reformatter_only_and_hot_editor_is_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_root = repo_root / "src" / "offline_companion"
    production_hits: list[Path] = []
    for path in source_root.rglob("*.py"):
        if "tone_keywords" in path.read_text(encoding="utf-8"):
            production_hits.append(path.relative_to(repo_root))
    shell_source = (
        source_root / "shell" / "ui_host" / "desktop" / "static" / "shell.js"
    ).read_text(encoding="utf-8")
    shell_api_source = (
        source_root / "shell" / "ui_host" / "desktop" / "static" / "shell_api.js"
    ).read_text(encoding="utf-8")

    assert production_hits == [
        Path("src/offline_companion/core/local_reformatter/rule_reformatter.py")
    ]
    assert "personaEditBtn" not in shell_source
    assert "togglePersonaEdit" not in shell_source
    assert "savePersonaEdit" not in shell_source
    assert "_deriveTraits" not in shell_source
    assert "_genDesc" not in shell_source
    assert "_genAnchor" not in shell_source
    assert "previewPersonaApi" in shell_source
    assert "_deriveTraits" not in shell_api_source
    assert "/api/personas/preview" in shell_api_source
    save_block = shell_source[
        shell_source.index("async function savePersona") : shell_source.index(
            "var _currentMemoryCard"
        )
    ]
    assert "traits:" not in save_block
    assert "_personaRegistry[name] =" not in save_block
